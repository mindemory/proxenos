// Server side of the Ask page. Import only from route handlers.
//
// A question is checked here, then handed to `proxenos ask` as one JSON line on its stdin (never
// its arguments, its environment, a URL or a log: it may be someone's private message). That runs
// in the background through the same jobs as the Connect page's; the page follows it by reading
// the files `proxenos ask` writes, clones/ask/<id>.json, first as "working" and then as it ended.
// Each file is read field by field, so nothing else in it reaches the page.

import { constants as fsConstants, promises as fs } from "node:fs";
import path from "node:path";

import { ASK_MS, askJobs, startJob, type Job } from "./connect";
import {
  ASK_IMAGE_TYPES,
  ASK_MAX_IMAGE_BYTES,
  ASK_MAX_IMAGES,
  ASK_MAX_TEXT,
  type AskDraft,
  type AskEntry,
  type AskImage,
  type AskImageType,
  type AskJob,
  type AskResponse,
  type AskStatus,
} from "./types";
import { nowIso, vaultInfo, vaultPath } from "./vault";

const MAX_ASKS = 20;
/** An ask's file is text and a transcription: a few KB. One far beyond that isn't read. */
const MAX_ASK_BYTES = 2 * 1024 * 1024;
const ASK_ID = /^[A-Za-z0-9_-]{1,64}$/;
const STATUSES: readonly AskStatus[] = ["working", "done", "failed"];
/**
 * How far an ask's time may read from its command's. The ask writes it after its command has
 * started (a second may be rounded away), and the command can end a moment before the ask's last
 * write is seen.
 */
const BEFORE_MS = 1000;
const AFTER_MS = 5000;

/**
 * The most a question's request may weigh: every screenshot at its largest as base64, and the
 * text at its longest with every character escaped. Anything bigger is refused unread.
 */
export const ASK_MAX_BODY = ASK_MAX_IMAGES * Math.ceil(ASK_MAX_IMAGE_BYTES / 3) * 4 + ASK_MAX_TEXT * 6 + 4096;

// ── The question ────────────────────────────────────────────────────────────

const BASE64 = /^[A-Za-z0-9+/]+={0,2}$/;

/** Whether the bytes at the start of an image are the ones its type begins with. */
function looksLike(type: AskImageType, head: Buffer): boolean {
  switch (type) {
    case "image/png":
      return head.subarray(0, 4).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47]));
    case "image/jpeg":
      return head.subarray(0, 3).equals(Buffer.from([0xff, 0xd8, 0xff]));
    case "image/webp":
      return head.subarray(0, 4).toString("latin1") === "RIFF" && head.subarray(8, 12).toString("latin1") === "WEBP";
  }
}

/** One screenshot, or why it won't do. The base64 is checked as text; it isn't decoded in full. */
function toImage(raw: unknown): AskImage | string {
  const bad = "A screenshot must be a PNG, JPEG or WebP image, sent as base64.";
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return bad;
  const { type, data } = raw as Record<string, unknown>;
  const kind = ASK_IMAGE_TYPES.find((t) => t === type);
  if (!kind || typeof data !== "string") return bad;
  // Canonical base64: whole groups of four, padding only at the end.
  if (data.length < 16 || data.length % 4 !== 0 || !BASE64.test(data)) return bad;
  const padding = data.endsWith("==") ? 2 : data.endsWith("=") ? 1 : 0;
  if ((data.length / 4) * 3 - padding > ASK_MAX_IMAGE_BYTES) {
    return `A screenshot is over ${ASK_MAX_IMAGE_BYTES / 1024 / 1024} MB.`;
  }
  if (!looksLike(kind, Buffer.from(data.slice(0, 16), "base64"))) return bad;
  return { type: kind, data };
}

/** A question as `proxenos ask` takes it. */
export interface Question {
  text: string;
  images: AskImage[];
  /** Research it and think it through, rather than answer quickly. */
  deep: boolean;
}

/** The question in a request's body, or why it can't be asked. Anything else in the body is dropped. */
export function parseAsk(body: Record<string, unknown>): Question | { error: string } {
  const raw = body.text ?? "";
  if (typeof raw !== "string") return { error: "text must be a string." };
  if (raw.length > ASK_MAX_TEXT) return { error: `Keep the question to ${ASK_MAX_TEXT.toLocaleString("en-US")} characters.` };
  const list = body.images ?? [];
  if (!Array.isArray(list)) return { error: "images must be a list." };
  if (list.length > ASK_MAX_IMAGES) return { error: `Add at most ${ASK_MAX_IMAGES} screenshots.` };
  const images: AskImage[] = [];
  for (const item of list) {
    const image = toImage(item);
    if (typeof image === "string") return { error: image };
    images.push(image);
  }
  const text = raw.trim();
  if (!text && images.length === 0) return { error: "Ask something, or add a screenshot." };
  return { text, images, deep: body.deep === true };
}

/** Whether a value is an ask's id, as `proxenos ask` makes them. */
export function isAskId(value: unknown): value is string {
  return typeof value === "string" && /^ask-\d{8}T\d{6}Z$/.test(value);
}

/**
 * Start `proxenos ask` on a question that passed parseAsk(), with the question on its stdin as one
 * line. Null when an ask is already running.
 */
export function startAsk(question: Question): Promise<Job | null> {
  return startJob("ask", ["ask"], null, JSON.stringify(question) + "\n");
}

/**
 * Think an earlier quick ask through: `proxenos ask` reads its question and kept screenshots from
 * the vault. Null when an ask is already running.
 */
export function startAgain(id: string): Promise<Job | null> {
  return startJob("ask", ["ask"], null, JSON.stringify({ again: id }) + "\n");
}

// ── The answers ─────────────────────────────────────────────────────────────

function str(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

function toDraft(raw: unknown): AskDraft | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const body = str(r.body)?.trim();
  if (!body) return null;
  return { to: str(r.to)?.trim() ?? "", channel: (str(r.channel) ?? "").trim().toLowerCase(), body };
}

function toAsk(raw: unknown): AskEntry | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const id = str(r.id);
  const status = STATUSES.find((s) => s === r.status);
  if (!id || !ASK_ID.test(id) || !status) return null;
  const n = r.images;
  return {
    id,
    at: str(r.at) ?? "",
    status,
    // Asks from before quick answers say nothing of it, and were all thought through.
    deep: r.deep !== false,
    question: str(r.question) ?? "",
    images: typeof n === "number" && Number.isInteger(n) && n > 0 ? n : 0,
    seen: str(r.seen) ?? "",
    answer: str(r.answer) ?? "",
    draft: toDraft(r.draft),
    found: str(r.found)?.trim() ?? "",
    asks: Array.isArray(r.asks) ? r.asks.filter((a): a is string => typeof a === "string" && a.trim() !== "").slice(0, 20) : [],
    error: str(r.error)?.trim() || null,
  };
}

/** Parse a plain file, never a symlink, or null when it's missing, too large or malformed. */
async function readPlainJson(file: string): Promise<unknown> {
  try {
    // O_NOFOLLOW: a file swapped for a symlink since the listing isn't followed either.
    const fh = await fs.open(file, fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW);
    try {
      const st = await fh.stat();
      if (!st.isFile() || st.size > MAX_ASK_BYTES) return null;
      return JSON.parse(await fh.readFile("utf8"));
    } finally {
      await fh.close();
    }
  } catch {
    return null;
  }
}

/** What an ask that never wrote its end says: how its command ended, or that it vanished. */
function whyUnfinished(job: Job | null): string {
  if (job?.state === "stopped") return "Stopped.";
  if (job?.state === "failed") return job.message || "It stopped before it finished.";
  return "It didn't finish.";
}

/**
 * An ask whose file still says "working" but whose command is over would spin on the page for
 * ever: it's shown as failed instead, with how its command ended. Its command is the newest one
 * that began before it did. An ask older than the command now running was left behind by one that
 * was killed; and any that has been going on for longer than a command is allowed to has been too.
 * `jobs` are the server's recent asks, newest first.
 */
function settled(entry: AskEntry, since: number, jobs: Job[], nowMs: number): AskEntry {
  if (entry.status !== "working") return entry;
  const failed = (error: string): AskEntry => ({ ...entry, status: "failed", error });
  const mine = jobs.find((j) => Date.parse(j.started) - BEFORE_MS <= since);
  if (mine && mine.state !== "running" && since <= Date.parse(mine.finished ?? "") + AFTER_MS) {
    return failed(whyUnfinished(mine));
  }
  const now = jobs[0];
  if (now?.state === "running" && since < Date.parse(now.started) - BEFORE_MS) return failed("It didn't finish.");
  return nowMs - since > ASK_MS + 60_000 ? failed("It didn't finish.") : entry;
}

/** The twenty newest asks from clones/ask, newest first, and how the server's latest ask stands. */
export async function getAsks(): Promise<AskResponse> {
  const vault = vaultPath();
  const dir = path.join(vault, "clones", "ask");
  let names: string[] = [];
  try {
    names = (await fs.readdir(dir)).filter((n) => n.endsWith(".json") && !n.startsWith("."));
  } catch {
    // No asks yet.
  }
  const files: { name: string; mtime: number }[] = [];
  for (const name of names) {
    try {
      const st = await fs.lstat(path.join(dir, name));
      if (st.isFile() && st.size <= MAX_ASK_BYTES) files.push({ name, mtime: st.mtimeMs });
    } catch {
      // Vanished: skip it.
    }
  }
  files.sort((a, b) => b.mtime - a.mtime || b.name.localeCompare(a.name));

  const jobs = askJobs();
  const job = jobs[0] ?? null;
  const nowMs = Date.now();
  const seen = new Set<string>();
  const rows: { entry: AskEntry; since: number }[] = [];
  for (const { name, mtime } of files.slice(0, MAX_ASKS)) {
    const entry = toAsk(await readPlainJson(path.join(dir, name)));
    if (!entry || seen.has(entry.id)) continue;
    seen.add(entry.id);
    const since = Date.parse(entry.at) || mtime;
    rows.push({ entry: settled(entry, since, jobs, nowMs), since });
  }
  rows.sort((a, b) => b.since - a.since || b.entry.id.localeCompare(a.entry.id));

  const view: AskJob | null = job && {
    state: job.state,
    message: job.message,
    started: job.started,
    finished: job.finished,
    // The command's last line is the id of the ask it finished.
    id: job.state === "done" && ASK_ID.test(job.message) ? job.message : null,
  };
  return { now: nowIso(), vault: await vaultInfo(vault), asks: rows.map((r) => r.entry), job: view };
}
