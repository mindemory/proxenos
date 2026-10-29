// Server side of the Errands page. Import only from route handlers.
//
// An errand is started by handing its goal to `proxenos clone errands -` as one JSON line on its
// stdin (never its arguments: it may name someone and why), and the page follows it by reading
// clones/errands/<id>.json, which the command writes after every step. A Send or a Drop goes the
// same way, as its own job, so one can go out while another errand is still being carried out.
// Each file is read field by field, so nothing else in it reaches the page; where the CV sits on
// disk, and the chat a message would go to, stay on the Mac.

import { constants as fsConstants, promises as fs } from "node:fs";
import path from "node:path";

import { ASK_MS, latestJob, startJob, type Job } from "./connect";
import {
  ERRAND_MAX_GOAL,
  ERRAND_MAX_MESSAGE,
  type Errand,
  type ErrandCv,
  type ErrandEdits,
  type ErrandJob,
  type ErrandMessage,
  type ErrandsResponse,
  type ErrandStatus,
  type ErrandStep,
} from "./types";
import { nowIso, vaultInfo, vaultPath } from "./vault";

const MAX_ERRANDS = 30;
const MAX_ERRAND_BYTES = 1024 * 1024;
const ERRAND_ID = /^errand-\d{8}T\d{6}Z$/;
const STATUSES: readonly ErrandStatus[] = ["working", "ready", "waiting", "sent", "failed", "dropped"];
const ADDRESS = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$/;

/** The most an errand's request may weigh: a message at its longest with every character escaped. */
export const ERRAND_MAX_BODY = ERRAND_MAX_MESSAGE * 6 + 4096;

// ── Requests ────────────────────────────────────────────────────────────────

export function isErrandId(value: unknown): value is string {
  return typeof value === "string" && ERRAND_ID.test(value);
}

/** The goal in a request's body, or why it can't be started. */
export function parseGoal(body: Record<string, unknown>): string | { error: string } {
  const goal = typeof body.goal === "string" ? body.goal.trim() : "";
  if (!goal) return { error: "Say what the errand is." };
  if (goal.length > ERRAND_MAX_GOAL)
    return {
      error: `Keep it to ${ERRAND_MAX_GOAL.toLocaleString("en-US")} characters.`,
    };
  return goal;
}

/** A Send in a request's body: which message, and the edits to make to it first. */
export function parseSend(body: Record<string, unknown>): ({ send: string; index: number } & ErrandEdits) | { error: string } {
  if (!isErrandId(body.send)) return { error: "send must be an errand's id." };
  const index = body.index;
  if (typeof index !== "number" || !Number.isInteger(index) || index < 0 || index > 9)
    return { error: "index must be a message's number." };
  const edits: ErrandEdits = {};
  for (const key of ["address", "subject", "body"] as const) {
    const value = body[key];
    if (value === undefined) continue;
    if (typeof value !== "string" || value.length > ERRAND_MAX_MESSAGE) return { error: `${key} must be text.` };
    edits[key] = value;
  }
  if (edits.address !== undefined && edits.address.trim() && !ADDRESS.test(edits.address.trim())) {
    return { error: "That isn't an email address." };
  }
  if (edits.body !== undefined && !edits.body.trim()) return { error: "The message is empty." };
  return {
    send: body.send,
    index,
    ...edits,
    ...(edits.address !== undefined && { address: edits.address.trim() }),
  };
}

/** Carry out an errand. Null when one is already being carried out. */
export function startErrand(goal: string): Promise<Job | null> {
  return startJob("errand", ["clone", "errands", "-"], null, JSON.stringify({ goal }) + "\n");
}

/** Send one of an errand's messages, or drop the errand. Null when a Send is still going. */
export function startSend(request: ({ send: string; index: number } & ErrandEdits) | { drop: string }): Promise<Job | null> {
  return startJob("send", ["clone", "errands", "-"], null, JSON.stringify(request) + "\n");
}

// ── The errands ─────────────────────────────────────────────────────────────

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function strings(v: unknown, limit: number): string[] {
  return Array.isArray(v) ? v.filter((s): s is string => typeof s === "string" && s.trim() !== "").slice(0, limit) : [];
}

function toStep(raw: unknown): ErrandStep | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const title = str(r.title).trim();
  return title ? { at: str(r.at), title, detail: str(r.detail) } : null;
}

function toMessage(raw: unknown): ErrandMessage | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const body = str(r.body);
  if (!body.trim()) return null;
  return {
    role: r.role === "intro" ? "intro" : "main",
    to: str(r.to),
    channel: str(r.channel) || "email",
    address: str(r.address),
    via: r.via === "apple_mail" || r.via === "beeper" ? r.via : "",
    evidence: str(r.evidence),
    subject: str(r.subject),
    body,
    attach: r.attach === true,
    state: r.state === "ready" || r.state === "sent" ? r.state : "waiting",
    sentAt: str(r.sent_at),
  };
}

function toCv(raw: unknown): ErrandCv | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const name = str(r.name);
  // Its path on disk stays here: the page shows only its name, date and where it was found.
  return name
    ? {
        name,
        made: str(r.made),
        where: str(r.where),
        notes: strings(r.notes, 10),
      }
    : null;
}

function toErrand(raw: unknown): Errand | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const status = STATUSES.find((s) => s === r.status);
  if (!isErrandId(r.id) || !status) return null;
  const steps = Array.isArray(r.steps) ? r.steps.map(toStep).filter((s): s is ErrandStep => s !== null) : [];
  const messages = Array.isArray(r.messages) ? r.messages.map(toMessage).filter((m): m is ErrandMessage => m !== null) : [];
  return {
    id: r.id,
    goal: str(r.goal),
    created: str(r.created),
    updated: str(r.updated),
    status,
    summary: str(r.summary),
    who: str(r.who),
    why: str(r.why),
    needs: strings(r.needs, 5),
    cv: toCv(r.cv),
    steps: steps.slice(0, 50),
    messages: messages.slice(0, 4),
    error: str(r.error) || null,
  };
}

async function readPlainJson(file: string): Promise<unknown> {
  try {
    // O_NOFOLLOW: a file swapped for a symlink since the listing isn't followed either.
    const fh = await fs.open(file, fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW);
    try {
      const st = await fh.stat();
      if (!st.isFile() || st.size > MAX_ERRAND_BYTES) return null;
      return JSON.parse(await fh.readFile("utf8"));
    } finally {
      await fh.close();
    }
  } catch {
    return null;
  }
}

function toJob(job: Job | null): ErrandJob | null {
  return (
    job && {
      state: job.state,
      message: job.message,
      started: job.started,
      finished: job.finished,
    }
  );
}

/** The newest errands, newest first, leaving out those dropped, and how the jobs stand. */
export async function getErrands(): Promise<ErrandsResponse> {
  const vault = vaultPath();
  const dir = path.join(vault, "clones", "errands");
  let names: string[] = [];
  try {
    names = (await fs.readdir(dir)).filter((n) => ERRAND_ID.test(n.replace(/\.json$/, "")) && n.endsWith(".json"));
  } catch {
    // No errands yet.
  }
  // The id is when it began, so the newest sort last by name.
  names.sort().reverse();
  const job = latestJob("errand");
  const errands: Errand[] = [];
  for (const name of names.slice(0, MAX_ERRANDS)) {
    const errand = toErrand(await readPlainJson(path.join(dir, name)));
    if (!errand || errand.status === "dropped") continue;
    // Still "working" with nothing carrying it out: the page's command for it ended without
    // saying so, or (one started elsewhere, from the command line) no step in longer than an
    // errand may take.
    const created = Date.parse(errand.created);
    const ended =
      job !== null && job.state !== "running" && Date.parse(job.started) <= created + 5000 && created <= Date.parse(job.finished ?? "");
    const stale = Date.now() - (Date.parse(errand.updated) || created) > ASK_MS;
    if (errand.status === "working" && (ended || stale)) {
      errand.status = "failed";
      errand.error = (ended && job.state === "failed" && job.message) || "It didn't finish.";
    }
    errands.push(errand);
  }
  return {
    now: nowIso(),
    vault: await vaultInfo(vault),
    errands,
    job: toJob(job),
    sending: toJob(latestJob("send")),
  };
}
