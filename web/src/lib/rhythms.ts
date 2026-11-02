// Server side of the Rhythms view. Import only from route handlers.
//
// The page reads the weeks through `proxenos clone rhythms --json`, which counts again only the
// month files that changed since it last ran (the first run over years of records takes longer)
// and asks no model. Its answer is read field by field, so nothing else in it reaches the page:
// counts, hours and km, the channels' names, the artists' names and their genres and moods.

import { lastLine, NO_COMMAND } from "./connect";
import type {
  RhythmsLine,
  RhythmsMove,
  RhythmsRange,
  RhythmsResolution,
  RhythmsResponse,
  RhythmsWeek,
} from "./types";
import { nowIso, proxenos, vaultInfo, vaultPath } from "./vault";

const COUNT_MS = 5 * 60_000; // the first count reads every month file: a minute or two over years
const MAX_OUTPUT = 64 * 1024 * 1024;
const WEEK = /^\d{4}-W\d{2}$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const RANGES: RhythmsRange[] = ["3m", "1y", "all"];
const RESOLUTIONS: RhythmsResolution[] = ["1w", "2w", "1m"];
const KINDS = new Set<RhythmsLine["kind"]>(["listening", "riding", "messages", "mood"]);

function record(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function num(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : 0;
}

function str(v: unknown, max = 200): string {
  return typeof v === "string" ? v.slice(0, max) : "";
}

/** A {name: number} map, at most `max` entries, numbers only. */
function counts(v: unknown, max = 40): Record<string, number> {
  const found: Record<string, number> = {};
  for (const [k, n] of Object.entries(record(v)).slice(0, max)) found[k.slice(0, 80)] = num(n);
  return found;
}

function move(v: unknown): RhythmsMove {
  const r = record(v);
  return { count: num(r.count), km: num(r.km), hours: num(r.hours) };
}

function toWeek(raw: unknown): RhythmsWeek | null {
  const r = record(raw);
  const week = str(r.week);
  const start = str(r.start);
  if (!WEEK.test(week) || !DAY.test(start)) return null;
  const heard = record(r.listening);
  const moved = record(r.movement);
  const said = record(r.messages);
  const met = record(r.calendar);
  return {
    week,
    start,
    listening: {
      hours: num(heard.hours),
      spoken_hours: num(heard.spoken_hours),
      plays: num(heard.plays),
      artists: num(heard.artists),
      top: (Array.isArray(heard.top) ? heard.top : [])
        .slice(0, 5)
        .map((a) => ({ name: str(record(a).name), hours: num(record(a).hours) }))
        .filter((a) => a.name),
      genres: counts(heard.genres),
      moods: counts(heard.moods),
      top_genre: str(heard.top_genre, 40) || null,
      top_mood: str(heard.top_mood, 40) || null,
    },
    movement: {
      rides: { ...move(moved.rides), climb_m: num(record(moved.rides).climb_m) },
      runs: move(moved.runs),
      hikes: move(moved.hikes),
      walks: move(moved.walks),
      other: { count: num(record(moved.other).count), hours: num(record(moved.other).hours) },
    },
    messages: { sent: counts(said.sent), received: counts(said.received), people: num(said.people) },
    calendar: { events: num(met.events), hours: num(met.hours) },
  };
}

function toLines(v: unknown): RhythmsLine[] {
  return (Array.isArray(v) ? v : [])
    .map((l) => ({ kind: str(record(l).kind) as RhythmsLine["kind"], text: str(record(l).text, 600) }))
    .filter((l) => KINDS.has(l.kind) && l.text);
}

function empty(): RhythmsResponse["stands_out"] {
  const none = () => ({ "1w": [], "2w": [], "1m": [] });
  return { "3m": none(), "1y": none(), all: none() };
}

/** The weeks, from `proxenos clone rhythms --json`; an empty answer with why, when there's none. */
export async function getRhythms(): Promise<RhythmsResponse> {
  const vault = vaultPath();
  const info = await vaultInfo(vault);
  const answer: RhythmsResponse = {
    now: nowIso(),
    vault: info,
    today: "",
    weeks: [],
    people: { "2w": {}, "1m": {} },
    channels: [],
    coverage: { share: 0, artists: 0, labelled: 0 },
    model: false,
    stands_out: empty(),
    error: null,
  };
  if (!info.exists) return answer;
  const cli = await proxenos();
  if (!cli) return { ...answer, error: NO_COMMAND };
  const ran = await new Promise<{ out: string } | { error: string }>((resolve) => {
    cli.exec(["clone", "rhythms", "--json"], { timeout: COUNT_MS, maxBuffer: MAX_OUTPUT }, (error, stdout, stderr) => {
      if (!error) resolve({ out: stdout });
      else resolve({ error: error.killed ? "It took too long." : lastLine(stderr) || lastLine(stdout) || "It failed." });
    });
  });
  if ("error" in ran) return { ...answer, error: `Couldn't count your weeks: ${ran.error}` };
  let r: Record<string, unknown>;
  try {
    r = record(JSON.parse(ran.out));
  } catch {
    return { ...answer, error: "proxenos clone rhythms gave an answer this page can't read." };
  }
  const people = record(r.people);
  const coverage = record(r.coverage);
  const stands = record(r.stands_out);
  const out = empty();
  for (const range of RANGES) for (const res of RESOLUTIONS) out[range][res] = toLines(record(stands[range])[res]);
  return {
    ...answer,
    today: DAY.test(str(r.today)) ? str(r.today) : "",
    weeks: (Array.isArray(r.weeks) ? r.weeks : []).map(toWeek).filter((w): w is RhythmsWeek => w !== null),
    people: { "2w": counts(people["2w"], 100_000), "1m": counts(people["1m"], 100_000) },
    channels: (Array.isArray(r.channels) ? r.channels : []).map((c) => str(c, 40)).filter(Boolean).slice(0, 20),
    coverage: { share: Math.min(1, num(coverage.share)), artists: num(coverage.artists), labelled: num(coverage.labelled) },
    model: r.model === true,
    stands_out: out,
  };
}
