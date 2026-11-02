// Server side of the Life view. Import only from route handlers.
//
// The page reads clones/life/ as the life clone writes it: each month's diary (months/YYYY-MM.json:
// a summary, entries by day and highlights, or a story from before there were entries) and how
// many records each day holds (calendar.json), field by field, so nothing else in them
// reaches the page. When the memory index is newer than that count, `proxenos clone life
// --calendar` counts again first (only the month files the index read again, so it's quick). A
// month's days come from `proxenos clone life --days YYYY-MM`: titles, names, counts and the
// opening of the user's own words, with no model. "Write this month" runs `proxenos clone life
// --month YYYY-MM` as the job "life", one at a time, and the page follows it through GET /api/life.

import { promises as fs } from "node:fs";
import path from "node:path";

import { lastLine, latestJob, NO_COMMAND, startJob, type Job } from "./connect";
import type { LifeDay, LifeEntry, LifeJob, LifeMonth, LifeResponse, LifeStory, LifeWrote } from "./types";
import { nowIso, proxenos, readJsonFile, vaultInfo, vaultPath } from "./vault";

const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const COUNT_MS = 2 * 60_000; // the first count reads the whole index: seconds, a minute at most
const DAYS_MS = 60_000;
const MAX_CALENDAR_BYTES = 64 * 1024 * 1024;
const MAX_STORY_BYTES = 256 * 1024;
const MAX_DAYS_OUTPUT = 16 * 1024 * 1024;
const OPENING = 360; // characters of a summary's first paragraph in the list
const MAX_ENTRIES = 31; // a month's diary entries, one a day at most
// Days with records a month needs before the night writes it (the clone's MIN_DAYS); one with
// fewer waits for "Write this month".
const NIGHT_MIN_DAYS = 3;

export function isMonth(value: unknown): value is string {
  return typeof value === "string" && MONTH.test(value);
}

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function count(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) && v >= 0 ? Math.floor(v) : 0;
}

function strings(v: unknown, max = 20): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string").slice(0, max) : [];
}

function record(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

/** Today on this computer's clock, YYYY-MM-DD: the clone counts days in the same local time. */
function localToday(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

async function mtime(file: string): Promise<number | null> {
  try {
    return (await fs.stat(file)).mtimeMs;
  } catch {
    return null;
  }
}

/** `proxenos <args>`'s output, or why there's none. */
async function run(args: string[], timeout: number, maxBuffer = 1024 * 1024): Promise<{ out: string } | { error: string }> {
  const cli = await proxenos();
  if (!cli) return { error: NO_COMMAND };
  return new Promise((resolve) => {
    cli.exec(args, { timeout, maxBuffer }, (error, stdout, stderr) => {
      if (!error) resolve({ out: stdout });
      else resolve({ error: error.killed ? "It took too long." : lastLine(stderr) || lastLine(stdout) || "It failed." });
    });
  });
}

// ── What each day holds ─────────────────────────────────────────────────────

/** Records per day from calendar.json, counted again first when the index has changed since. */
async function calendar(vault: string): Promise<{ days: Record<string, number>; error: string | null }> {
  const file = path.join(vault, "clones", "life", "calendar.json");
  const [counted, indexed] = await Promise.all([mtime(file), mtime(path.join(vault, "memory", "index.sqlite"))]);
  let error: string | null = null;
  if (indexed !== null && (counted === null || counted < indexed)) {
    const ran = await run(["clone", "life", "--calendar"], COUNT_MS);
    if ("error" in ran) error = `Couldn't count the days again: ${ran.error}`;
  }
  const days: Record<string, number> = {};
  const raw = record(record(await readJsonFile(file, MAX_CALENDAR_BYTES))?.days);
  for (const [day, bySource] of Object.entries(raw ?? {})) {
    const sources = record(bySource);
    if (!DAY.test(day) || !sources) continue;
    days[day] = Object.values(sources).reduce<number>((sum, n) => sum + count(n), 0);
  }
  return { days, error };
}

// ── Stories ─────────────────────────────────────────────────────────────────

/** A month's diary entries, on days of that month and oldest first; null when it has none, as a story from before entries does. */
function toEntries(raw: unknown, month: string): LifeEntry[] | null {
  if (!Array.isArray(raw)) return null;
  const entries: LifeEntry[] = [];
  for (const item of raw.slice(0, MAX_ENTRIES)) {
    const r = record(item);
    const day = str(r?.day);
    const text = str(r?.text).trim();
    if (DAY.test(day) && day.startsWith(`${month}-`) && text) entries.push({ day, text });
  }
  return entries.sort((a, b) => a.day.localeCompare(b.day));
}

function toStory(raw: unknown, month: string): LifeStory | null {
  const r = record(raw);
  // A story written before there were entries is read as its summary, so it shows until the night writes it again.
  const summary = (str(r?.summary) || str(r?.story)).trim();
  const entries = toEntries(r?.entries, month);
  if (!r || (!summary && !entries?.length)) return null;
  return {
    month,
    generated: str(r.generated) || null,
    summary,
    entries,
    highlights: strings(r.highlights, 6).map((h) => h.trim()).filter(Boolean),
    days_with_records: count(r.days_with_records),
  };
}

async function stories(vault: string): Promise<Map<string, LifeStory>> {
  const dir = path.join(vault, "clones", "life", "months");
  let names: string[] = [];
  try {
    names = (await fs.readdir(dir)).filter((n) => n.endsWith(".json") && MONTH.test(n.slice(0, -5)));
  } catch {
    // No stories yet.
  }
  const found = new Map<string, LifeStory>();
  for (const name of names) {
    const month = name.slice(0, -5);
    const story = toStory(await readJsonFile(path.join(dir, name), MAX_STORY_BYTES), month);
    if (story) found.set(month, story);
  }
  return found;
}

function opening(story: string): string {
  const first = story.split(/\n\s*\n/)[0]?.trim() ?? "";
  if (first.length <= OPENING) return first;
  return first.slice(0, OPENING).replace(/\s+\S*$/, "") + "…";
}

// ── A month's days ──────────────────────────────────────────────────────────

function toWrote(raw: unknown): LifeWrote | null {
  const r = record(raw);
  const to = str(r?.to).trim();
  if (!r || !to) return null;
  return { to, channel: str(r.channel), count: count(r.count), said: str(r.said) };
}

function toDay(raw: unknown, month: string): LifeDay | null {
  const r = record(raw);
  const date = str(r?.date);
  if (!r || !DAY.test(date) || !date.startsWith(month)) return null;
  const sources: Record<string, number> = {};
  for (const [name, n] of Object.entries(record(r.sources) ?? {}).slice(0, 40)) sources[name] = count(n);
  const journal = record(r.journal);
  return {
    date,
    records: count(r.records),
    sources,
    wrote: (Array.isArray(r.wrote) ? r.wrote : []).slice(0, 30).map(toWrote).filter((w): w is LifeWrote => w !== null),
    events: strings(r.events),
    notes: strings(r.notes),
    activity: strings(r.activity),
    health: strings(r.health),
    other: strings(r.other),
    journal: journal ? { brief: str(journal.brief), next_up: strings(journal.next_up, 3) } : null,
  };
}

async function monthDays(month: string): Promise<{ days: LifeDay[]; error: string | null }> {
  const ran = await run(["clone", "life", "--days", month], DAYS_MS, MAX_DAYS_OUTPUT);
  if ("error" in ran) return { days: [], error: `Couldn't read the days of ${month}: ${ran.error}` };
  try {
    const answer = record(JSON.parse(ran.out));
    const days = Array.isArray(answer?.days) ? answer.days : [];
    return { days: days.map((d) => toDay(d, month)).filter((d): d is LifeDay => d !== null), error: null };
  } catch {
    return { days: [], error: "proxenos clone life gave an answer this page can't read." };
  }
}

// ── The view ────────────────────────────────────────────────────────────────

function toJob(job: Job | null): LifeJob | null {
  return job && { state: job.state, message: job.message, month: job.account, started: job.started, finished: job.finished };
}

/** Every month with records or a story, newest first, and, with `month`, that month's story and days. */
export async function getLife(month: string | null): Promise<LifeResponse> {
  const vault = vaultPath();
  const today = localToday();
  const [{ days, error }, written] = await Promise.all([calendar(vault), stories(vault)]);
  const held = new Map<string, { days: number; records: number }>();
  for (const [day, n] of Object.entries(days)) {
    if (day > today) continue; // a calendar runs ahead of the day
    const m = held.get(day.slice(0, 7)) ?? { days: 0, records: 0 };
    held.set(day.slice(0, 7), { days: m.days + 1, records: m.records + n });
  }
  const months: LifeMonth[] = [...new Set([...held.keys(), ...written.keys()])]
    .sort()
    .reverse()
    .map((m) => {
      const story = written.get(m);
      return {
        month: m,
        // The diary counts walks and listening too, which the index keeps a month at a time.
        days: Math.max(held.get(m)?.days ?? 0, story?.days_with_records ?? 0),
        records: held.get(m)?.records ?? 0,
        written: story?.generated ?? null,
        opening: story ? opening(story.summary) : "",
        highlights: story?.highlights.slice(0, 3) ?? [],
      };
    });
  let open: LifeResponse["open"] = null;
  let problem = error;
  if (month) {
    const found = await monthDays(month);
    open = { month, story: written.get(month) ?? null, days: found.days };
    problem = problem ?? found.error;
  }
  return {
    now: nowIso(),
    vault: await vaultInfo(vault),
    today,
    months,
    // A story from before there were entries is written again too.
    left: months.filter((m) => !written.get(m.month)?.entries && m.days >= NIGHT_MIN_DAYS && m.month < today.slice(0, 7)).length,
    open,
    job: toJob(latestJob("life")),
    error: problem,
  };
}

/** Write one month's story in the background. Null when one is being written already. */
export async function startMonth(month: string): Promise<LifeJob | null> {
  return toJob(await startJob("life", ["clone", "life", "--month", month], month));
}
