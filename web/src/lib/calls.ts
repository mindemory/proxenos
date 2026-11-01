// Server side of the Calls page. Import only from route handlers.
//
// A call sheet is clones/calls/<id>.md; a call from it writes clones/calls/<id>/live.json as it
// goes and <id>/<started>.json once it's over (src/proxenos/calls.py). The page starts a call as a
// process of its own, `proxenos call start <id>`, apart from the page's, so it goes on if the page
// restarts, and hangs up with `proxenos call stop <id>`. Nothing here dials: only the command does,
// and only when the user presses Call. The values of a sheet's facts (a date of birth, an account
// number) never reach the page, only their names.

import { execFile, spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import path from "node:path";

import { NO_COMMAND } from "./connect";
import type { CallLine, CallOutcome, CallPhase, CallRecord, CallSheet, CallsResponse } from "./types";
import { nowIso, proxenosBin, readJsonFile, REPO_ROOT, setting, vaultInfo, vaultPath } from "./vault";

/** A sheet's id: its file name. Never starting with "-", so the command can't take it for an option. */
export const CALL_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
const MAX_SHEETS = 50;
const MAX_SHEET_BYTES = 64 * 1024;
const MAX_RECORD_BYTES = 2 * 1024 * 1024;
const MAX_LINES = 600;
const PAST = 5;
/** The command first checks that Twilio can reach this Mac, which may take 15 seconds. */
const START_MS = 30_000;
const STOP_MS = 30_000;
const LOG = "start.log";
const NUMBER = /^\+[1-9]\d{6,14}$/;
const PHASES: readonly CallPhase[] = ["dialing", "menu", "waiting", "talking", "connecting", "connected", "done"];
const WHO: ReadonlySet<string> = new Set(["them", "assistant", "line", "note"]);
/** What calls need besides the Twilio secrets, which only the command can see in the Keychain. */
const NEEDED: readonly [string, string][] = [
  ["TWILIO_NUMBER", "PROXENOS_TWILIO_NUMBER"],
  ["PHONE", "PROXENOS_PHONE"],
  ["CALLS_URL", "PROXENOS_CALLS_URL"],
  ["NAME", "PROXENOS_NAME"],
];

type Result = { ok: true; message: string } | { ok: false; status: number; error: string };

function folder(vault: string): string {
  return path.join(vault, "clones", "calls");
}

export async function getCalls(): Promise<CallsResponse> {
  const vault = vaultPath();
  let names: string[] = [];
  try {
    names = (await fs.readdir(folder(vault))).filter((n) => n.endsWith(".md") && CALL_ID.test(n.slice(0, -3)));
  } catch {
    // No sheets yet.
  }
  const sheets = await Promise.all(names.sort().slice(0, MAX_SHEETS).map((n) => readSheet(vault, n.slice(0, -3))));
  return {
    now: nowIso(),
    vault: await vaultInfo(vault),
    missing: NEEDED.filter(([name]) => !setting(name)).map(([, variable]) => variable),
    sheets,
  };
}

/** Front matter as calls.py reads it: "key: value" lines between two "---" lines, the first of each key. */
function frontMatter(text: string): { fields: Record<string, string>; body: string } | null {
  const match = /^---[ \t]*\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/.exec(text.replace(/^﻿/, ""));
  if (!match) return null;
  const fields: Record<string, string> = {};
  for (const line of match[1].split(/\r?\n/)) {
    const field = /^([A-Za-z_][\w-]*)\s*:\s*(.*)$/.exec(line);
    if (field && !(field[1].toLowerCase() in fields)) fields[field[1].toLowerCase()] = unquote(field[2]);
  }
  return { fields, body: text.replace(/^﻿/, "").slice(match[0].length).trim() };
}

function unquote(value: string): string {
  const v = value.trim();
  if (v.length >= 2 && v.startsWith('"') && v.endsWith('"')) {
    try {
      const parsed: unknown = JSON.parse(v);
      return typeof parsed === "string" ? parsed : v.slice(1, -1);
    } catch {
      return v.slice(1, -1);
    }
  }
  return v.length >= 2 && v.startsWith("'") && v.endsWith("'") ? v.slice(1, -1) : v;
}

function parsed(value: string | undefined): unknown {
  if (!value) return undefined;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

async function readSheet(vault: string, id: string): Promise<CallSheet> {
  const sheet: CallSheet = {
    id,
    title: id,
    to: "",
    number: "",
    about: "",
    asks: [],
    facts: [],
    talk: false,
    notes: "",
    error: null,
    live: await liveRecord(vault, id),
    past: await pastRecords(vault, id),
  };
  let text: string;
  try {
    const file = path.join(folder(vault), `${id}.md`);
    if ((await fs.stat(file)).size > MAX_SHEET_BYTES) return { ...sheet, error: "The sheet is too big to read." };
    text = await fs.readFile(file, "utf8");
  } catch {
    return { ...sheet, error: "The sheet couldn't be read." };
  }
  const front = frontMatter(text);
  if (!front) return { ...sheet, error: "The sheet has no front matter." };
  const f = front.fields;
  const number = (f.number ?? "").replace(/[ -]/g, "");
  const asks = parsed(f.asks) ?? [];
  const facts = parsed(f.facts) ?? {};
  const read: CallSheet = {
    ...sheet,
    title: (f.title ?? "").trim() || id,
    to: (f.to ?? "").trim() || number,
    number,
    about: (f.about ?? "").trim(),
    asks: Array.isArray(asks) ? asks.filter((a): a is string => typeof a === "string").slice(0, 20) : [],
    facts: facts && typeof facts === "object" && !Array.isArray(facts) ? Object.keys(facts).slice(0, 20) : [],
    talk: ["true", "yes"].includes((f.talk ?? "").trim().toLowerCase()),
    notes: front.body.slice(0, 4000),
  };
  if (!NUMBER.test(number)) return { ...read, error: "Its number needs the country code, like +16035550100." };
  if (!read.about) return { ...read, error: "It doesn't say what the call is about." };
  if (!Array.isArray(asks) || !facts || typeof facts !== "object" || Array.isArray(facts)) {
    return { ...read, error: "Its asks or facts aren't written the way calls.py reads them." };
  }
  return read;
}

function alive(pid: unknown): boolean {
  if (typeof pid !== "number" || !Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return (e as NodeJS.ErrnoException).code === "EPERM";
  }
}

async function readLive(vault: string, id: string): Promise<Record<string, unknown> | null> {
  try {
    const live = await readJsonFile(path.join(folder(vault), id, "live.json"), MAX_RECORD_BYTES);
    return live && typeof live === "object" && !Array.isArray(live) ? (live as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/** The call going from this sheet, if its process is still running. */
async function liveRecord(vault: string, id: string): Promise<CallRecord | null> {
  const live = await readLive(vault, id);
  return live && alive(live.pid) ? toRecord(live) : null;
}

async function pastRecords(vault: string, id: string): Promise<CallRecord[]> {
  let names: string[];
  try {
    names = (await fs.readdir(path.join(folder(vault), id))).filter((n) => /^\d{8}T\d{6}Z\.json$/.test(n));
  } catch {
    return [];
  }
  const records = await Promise.all(
    names
      .sort()
      .reverse()
      .slice(0, PAST)
      .map(async (n) => {
        try {
          return toRecord(await readJsonFile(path.join(folder(vault), id, n), MAX_RECORD_BYTES));
        } catch {
          return null;
        }
      }),
  );
  return records.filter((r): r is CallRecord => r !== null);
}

function str(v: unknown, max = 2000): string {
  return typeof v === "string" ? v.slice(0, max) : "";
}

function strings(v: unknown, max = 20): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string").slice(0, max).map((x) => x.slice(0, 500)) : [];
}

/** A call's file, field by field, so nothing else in it (its Twilio id, its process) reaches the page. */
function toRecord(raw: unknown): CallRecord | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const r = raw as Record<string, unknown>;
  const notes = (r.notes && typeof r.notes === "object" ? r.notes : {}) as Record<string, unknown>;
  const lines = Array.isArray(r.transcript) ? r.transcript.slice(-MAX_LINES) : [];
  const transcript: CallLine[] = lines.flatMap((l: unknown) => {
    if (!l || typeof l !== "object") return [];
    const line = l as Record<string, unknown>;
    return typeof line.who === "string" && WHO.has(line.who)
      ? [{ at: str(line.at, 40), who: line.who as CallLine["who"], text: str(line.text) }]
      : [];
  });
  return {
    started: str(r.started, 40),
    ended: str(r.ended, 40) || null,
    status: str(r.status, 40),
    phase: PHASES.includes(r.phase as CallPhase) ? (r.phase as CallPhase) : "done",
    mode: r.mode === "talk" ? "talk" : "ring",
    done: Array.isArray(r.done) ? r.done.filter((n): n is number => Number.isInteger(n)).slice(0, 20) : [],
    notes: { rep_name: str(notes.rep_name, 200), reference: str(notes.reference, 200), offered: strings(notes.offered) },
    transcript,
    outcome: toOutcome(r.outcome),
  };
}

function toOutcome(raw: unknown): CallOutcome | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const o = raw as Record<string, unknown>;
  const asks = Array.isArray(o.asks) ? o.asks : [];
  return {
    summary: str(o.summary),
    asks: asks.flatMap((a: unknown) => {
      const x = (a && typeof a === "object" ? a : {}) as Record<string, unknown>;
      return typeof x.ask === "string" ? [{ ask: str(x.ask, 500), result: str(x.result, 1000) }] : [];
    }),
    rep_name: str(o.rep_name, 200),
    reference: str(o.reference, 200),
    offered: strings(o.offered),
    next: strings(o.next),
  };
}

// ── Starting and stopping ───────────────────────────────────────────────────

async function lastLines(file: string): Promise<string> {
  try {
    const text = await fs.readFile(file, "utf8");
    return text.trim().split("\n").filter(Boolean).slice(-6).join("\n").slice(-800);
  } catch {
    return "";
  }
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Start `proxenos call start <id>` on its own, and wait until it says the call is going (its
 * live.json names it) or it stops, when what it printed says why: a setting missing, Twilio
 * unreachable or refusing.
 */
export async function startCall(id: string): Promise<Result> {
  const vault = vaultPath();
  const dir = path.join(folder(vault), id);
  try {
    await fs.access(path.join(folder(vault), `${id}.md`));
  } catch {
    return { ok: false, status: 404, error: "There's no call sheet by that name." };
  }
  if (await liveRecord(vault, id)) return { ok: false, status: 409, error: "A call from this sheet is already going." };
  const bin = await proxenosBin();
  if (!bin) return { ok: false, status: 500, error: NO_COMMAND };

  await fs.mkdir(dir, { recursive: true, mode: 0o700 });
  const logFile = path.join(dir, LOG);
  const log = await fs.open(logFile, "w", 0o600);
  let child;
  try {
    // Its own process group, so restarting the page doesn't hang up on whoever's on the line.
    child = spawn(bin, ["call", "start", id], { cwd: REPO_ROOT, detached: true, stdio: ["ignore", log.fd, log.fd] });
  } finally {
    await log.close();
  }
  child.unref();
  let code: number | null = null;
  child.on("exit", (c) => (code = c ?? 1));
  child.on("error", () => (code = 1));

  const deadline = Date.now() + START_MS;
  while (Date.now() < deadline) {
    await sleep(400);
    const live = await readLive(vault, id);
    if (live && live.pid === child.pid) return { ok: true, message: "Calling. It stays quiet on hold and rings you when someone answers." };
    if (code !== null) {
      const said = await lastLines(logFile);
      return code === 0
        ? { ok: true, message: said || "The call ended." }
        : { ok: false, status: 502, error: said || "The call didn't start." };
    }
  }
  return { ok: true, message: "Still starting the call; it shows here once it's going." };
}

/** Hang up the call going from this sheet, through `proxenos call stop <id>`. */
export async function stopCall(id: string): Promise<Result> {
  const bin = await proxenosBin();
  if (!bin) return { ok: false, status: 500, error: NO_COMMAND };
  return new Promise((resolve) => {
    execFile(bin, ["call", "stop", id], { cwd: REPO_ROOT, timeout: STOP_MS, maxBuffer: 64 * 1024 }, (error, stdout, stderr) => {
      const said = (error ? stderr || stdout : stdout).trim().split("\n").pop()?.slice(0, 400) ?? "";
      resolve(error ? { ok: false, status: 502, error: said || "Couldn't hang up." } : { ok: true, message: said || "Hung up." });
    });
  });
}
