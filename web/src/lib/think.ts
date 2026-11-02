// Server side of the Think page. Import only from route handlers.
//
// A message is checked here, then handed to `proxenos think` as one JSON line on its stdin (never
// its arguments, its environment, a URL or a log: it may hold anything). That runs in the
// background through the same jobs as the Ask page's, one at a time, and the page follows the job,
// cheaply, then reads the thread. Threads are read through the command too (`proxenos think
// --list` and `--show ID`), and its answer is read field by field, so nothing else reaches the page.

import { lastLine, latestJob, NO_COMMAND, startJob, type Job } from "./connect";
import {
  THINK_KINDS,
  THINK_MAX_TEXT,
  type ThinkContext,
  type ThinkJob,
  type ThinkKind,
  type ThinkMatter,
  type ThinkMessage,
  type ThinkResponse,
  type ThinkStatus,
  type ThinkStep,
  type ThinkSummary,
  type ThinkThread,
} from "./types";
import { nowIso, proxenos, vaultInfo, vaultPath } from "./vault";

// Reading threads is a file or a folder of them; the command itself takes a second to start.
const READ_MS = 60_000;
const MAX_OUTPUT = 16 * 1024 * 1024;
const THREAD_ID = /^think-\d{8}T\d{6}Z(?:-\d{1,3})?$/;
const MAX_ID = 200;
const STATUSES: readonly ThinkStatus[] = ["working", "done", "failed"];

/** The most a message's request may weigh: the text at its longest with every character escaped. */
export const THINK_MAX_BODY = THINK_MAX_TEXT * 6 * 2 + 4096;

/** Whether a value is a thread's id, as `proxenos think` makes them. */
export function isThreadId(value: unknown): value is string {
  return typeof value === "string" && THREAD_ID.test(value);
}

// ── A message ───────────────────────────────────────────────────────────────

/** A message as `proxenos think` takes it. */
export interface Say {
  text: string;
  /** The thread it goes on, or null for a new one. */
  thread: string | null;
  /** What a new thread starts from. */
  context: { kind: ThinkKind; id: string; text: string } | null;
}

/** The message in a request's body, or why it can't be sent. Anything else in the body is dropped. */
export function parseSay(body: Record<string, unknown>): Say | { error: string } {
  const raw = body.text ?? "";
  if (typeof raw !== "string") return { error: "text must be a string." };
  if (raw.length > THINK_MAX_TEXT) return { error: `Keep it to ${THINK_MAX_TEXT.toLocaleString("en-US")} characters.` };
  const text = raw.trim();
  const thread = body.thread ?? null;
  if (thread !== null && !isThreadId(thread)) return { error: "thread must be a thread's id." };
  // An empty message goes only to a thread, where it asks for its last answer again.
  if (!text && thread === null) return { error: "Write what you'd like to think through." };
  let context: Say["context"] = null;
  if (body.context != null) {
    if (thread !== null) return { error: "Only a new thread starts from something." };
    const c = body.context;
    if (typeof c !== "object" || Array.isArray(c)) return { error: "context must be an object." };
    const { kind, id, text: note } = c as Record<string, unknown>;
    const known = THINK_KINDS.find((k) => k === kind);
    if (!known) return { error: `context.kind must be one of ${THINK_KINDS.join(", ")}.` };
    if (id != null && (typeof id !== "string" || id.length > MAX_ID || /[\r\n]/.test(id))) return { error: "context.id isn't one." };
    if (note != null && (typeof note !== "string" || note.length > THINK_MAX_TEXT)) return { error: "context.text is too long." };
    context = { kind: known, id: typeof id === "string" ? id : "", text: typeof note === "string" ? note : "" };
  }
  return { text, thread, context };
}

/**
 * Start `proxenos think` on a message that passed parseSay(), with the message on its stdin as
 * one line. Null when Proxenos is already thinking one through.
 */
export function startThink(say: Say): Promise<Job | null> {
  return startJob("think", ["think"], say.thread, JSON.stringify(say) + "\n");
}

/** How the server's latest `proxenos think` stands. Its last line is the thread it answered. */
export function thinkJob(): ThinkJob | null {
  const job = latestJob("think");
  if (!job) return null;
  const finished = job.state === "done" && THREAD_ID.test(job.message) ? job.message : null;
  return {
    state: job.state,
    message: job.message,
    started: job.started,
    finished: job.finished,
    thread: finished ?? (isThreadId(job.account) ? job.account : null),
  };
}

// ── Threads ─────────────────────────────────────────────────────────────────

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function list(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function rec(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function toMatter(raw: unknown): ThinkMatter | null {
  const r = rec(raw);
  const text = str(r.text).trim();
  if (!text) return null;
  const record = str(r.record);
  return { text, source: str(r.source), label: str(r.label), record: record.length <= 512 ? record : "" };
}

function toStep(raw: unknown): ThinkStep | null {
  const r = rec(raw);
  const text = str(r.text).trim();
  return text ? { text, draftTo: str(r.draft_to).trim() } : null;
}

function toMessage(raw: unknown): ThinkMessage | null {
  const r = rec(raw);
  const role = r.role === "me" || r.role === "proxenos" ? r.role : null;
  const text = str(r.text);
  if (!role || !text.trim()) return null;
  const parts = rec(r.parts);
  return {
    role,
    at: str(r.at),
    text,
    matters: list(parts.matters).flatMap((m) => toMatter(m) ?? []),
    questions: list(parts.questions).filter((q): q is string => typeof q === "string" && q.trim() !== ""),
    next: list(parts.next).flatMap((s) => toStep(s) ?? []),
  };
}

function toContext(raw: unknown): ThinkContext | null {
  const r = rec(raw);
  const kind = THINK_KINDS.find((k) => k === r.kind);
  return kind ? { kind, id: str(r.id), title: str(r.title), text: str(r.text) } : null;
}

function toThread(raw: unknown): ThinkThread | null {
  const r = rec(raw);
  const id = str(r.id);
  const status = STATUSES.find((s) => s === r.status);
  if (!isThreadId(id) || !status) return null;
  return {
    id,
    title: str(r.title),
    created: str(r.created),
    updated: str(r.updated),
    status,
    error: str(r.error).trim() || null,
    context: toContext(r.context),
    messages: list(r.messages).flatMap((m) => toMessage(m) ?? []),
  };
}

function toSummary(raw: unknown): ThinkSummary | null {
  const r = rec(raw);
  const id = str(r.id);
  const status = STATUSES.find((s) => s === r.status);
  if (!isThreadId(id) || !status) return null;
  const turns = r.turns;
  return {
    id,
    title: str(r.title),
    updated: str(r.updated),
    status,
    kind: THINK_KINDS.find((k) => k === r.kind) ?? "",
    turns: typeof turns === "number" && Number.isInteger(turns) && turns >= 0 ? turns : 0,
    last: str(r.last),
  };
}

/** `proxenos think <args>`'s answer, parsed, or why there's none. */
async function run(args: string[]): Promise<{ data: unknown } | { error: string }> {
  const cli = await proxenos();
  if (!cli) return { error: NO_COMMAND };
  return new Promise((resolve) => {
    cli.exec(["think", ...args], { timeout: READ_MS, maxBuffer: MAX_OUTPUT }, (error, stdout, stderr) => {
      if (error) {
        resolve({ error: error.killed ? "It took too long." : lastLine(stderr) || lastLine(stdout) || "It failed." });
        return;
      }
      try {
        resolve({ data: JSON.parse(stdout) as unknown });
      } catch {
        resolve({ error: "proxenos think gave an answer this page can't read." });
      }
    });
  });
}

/**
 * Whether a thread whose file still says "working" was left so: no `proxenos think` runs (its
 * command was stopped, or the server restarted under it). Shown as failed, it can be asked again
 * rather than wait on the page for ever.
 */
function left(status: ThinkStatus, job: ThinkJob | null): boolean {
  return status === "working" && job?.state !== "running";
}

function whyLeft(job: ThinkJob | null): string {
  if (job?.state === "stopped") return "Stopped.";
  if (job?.state === "failed") return job.message || "It stopped before it finished.";
  return "It didn't finish.";
}

/** Every thread, newest first, and with `id`, that thread whole, and how the latest think stands. */
export async function getThink(id: string | null): Promise<ThinkResponse> {
  const vault = vaultPath();
  const job = thinkJob();
  const base = { now: nowIso(), vault: await vaultInfo(vault), job };
  if (!base.vault.exists) return { ...base, threads: [], thread: null, error: null };
  const [listed, shown] = await Promise.all([run(["--list"]), id ? run(["--show", id]) : null]);
  if ("error" in listed) return { ...base, threads: [], thread: null, error: listed.error };
  const threads = list(rec(listed.data).threads)
    .flatMap((t) => toSummary(t) ?? [])
    .map((t): ThinkSummary => (left(t.status, job) ? { ...t, status: "failed" } : t));
  let thread = shown && "data" in shown ? toThread(shown.data) : null;
  if (thread && left(thread.status, job)) thread = { ...thread, status: "failed", error: thread.error ?? whyLeft(job) };
  return { ...base, threads, thread, error: null };
}
