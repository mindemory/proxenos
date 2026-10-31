// Server side of the Projects page. Import only from route handlers.
//
// The page reads clones/projects/ as the clones write it: the user's list (projects.json), where
// each project stands (status.md), the steps the user queued (queue.json) and the steps taken
// (steps/<when>.json, with the figures and tables each made in steps/<when>/). Each file is read
// field by field, so nothing else in it reaches the page.
//
// Everything it asks for goes to `proxenos clone steps -` as one JSON line on its stdin: take a
// step now ({take}), which runs as the job "step", one at a time; and Accept, Discard, or a change
// to a queue, which run as the job "decide". Accept is the one request that changes the user's own
// code: it merges the step's branch into their checkout, and only when they press it.

import { constants as fsConstants, promises as fs } from "node:fs";
import path from "node:path";

import { latestJob, startJob, STEP_MS, type Job } from "./connect";
import {
  STEP_MAX_TEXT,
  type ProjectsJob,
  type ProjectsResponse,
  type ProjectStep,
  type QueuedStep,
  type StepFile,
  type StepMade,
  type StepNote,
  type StepStatus,
  type WorkProject,
} from "./types";
import { displayPath, expandHome, nowIso, vaultInfo, vaultPath } from "./vault";

const PROJECT_ID = /^[a-z0-9][a-z0-9-]{0,39}$/;
const WHEN = /^\d{8}-\d{6}$/;
const STEP_ID = /^([a-z0-9][a-z0-9-]{0,39})\/(\d{8}-\d{6})$/;
const MADE_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$/;
const STATUSES: readonly StepStatus[] = ["working", "ready", "failed", "accepted", "discarded"];
const STEPS_SHOWN = 8;
const MAX_JSON_BYTES = 1024 * 1024;
const MAX_STATUS_BYTES = 256 * 1024;
const MAX_MADE_BYTES = 25 * 1024 * 1024;

/** How a made file is served: images as themselves, everything else as plain text or a PDF, so nothing in one runs. */
const MADE_TYPES: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".svg": "image/svg+xml",
  ".pdf": "application/pdf",
  ".csv": "text/plain; charset=utf-8",
  ".tsv": "text/plain; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".md": "text/plain; charset=utf-8",
  ".json": "text/plain; charset=utf-8",
  ".html": "text/plain; charset=utf-8",
};
const IMAGE = new Set([".png", ".jpg", ".jpeg", ".gif", ".svg"]);

// ── Requests ────────────────────────────────────────────────────────────────

export function isProjectId(value: unknown): value is string {
  return typeof value === "string" && PROJECT_ID.test(value);
}

export function isStepId(value: unknown): value is string {
  return typeof value === "string" && STEP_ID.test(value);
}

export type Decision =
  | { accept: string }
  | { discard: string }
  | { queue: string; step: string }
  | { unqueue: string; id: string };

/** A decision in a request's body, or why it can't be made. */
export function parseDecision(body: Record<string, unknown>): Decision | { error: string } {
  if ("accept" in body) return isStepId(body.accept) ? { accept: body.accept } : { error: "accept must be a step's id." };
  if ("discard" in body) return isStepId(body.discard) ? { discard: body.discard } : { error: "discard must be a step's id." };
  if ("unqueue" in body) {
    if (!isProjectId(body.unqueue)) return { error: "unqueue must be a project's id." };
    return typeof body.id === "string" && /^q-[0-9a-f]{12}$/.test(body.id)
      ? { unqueue: body.unqueue, id: body.id }
      : { error: "id must be a queued step's id." };
  }
  if ("queue" in body) {
    if (!isProjectId(body.queue)) return { error: "queue must be a project's id." };
    const step = typeof body.step === "string" ? body.step.trim() : "";
    if (!step) return { error: "Say what the step is." };
    if (step.length > STEP_MAX_TEXT) return { error: `Keep it to ${STEP_MAX_TEXT.toLocaleString("en-US")} characters.` };
    return { queue: body.queue, step };
  }
  return { error: "Ask for take, queue, unqueue, accept or discard." };
}

/** Take a step on the project now. Null when a step is already being taken. */
export function startStep(project: string): Promise<Job | null> {
  return startJob("step", ["clone", "steps", "-"], project, JSON.stringify({ take: project }) + "\n");
}

/** Accept or discard a step, or change a queue. Null when another decision is still going. */
export function startDecision(decision: Decision): Promise<Job | null> {
  return startJob("decide", ["clone", "steps", "-"], null, JSON.stringify(decision) + "\n");
}

// ── Reading the vault ───────────────────────────────────────────────────────

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function strings(v: unknown, limit: number): string[] {
  return Array.isArray(v) ? v.filter((s): s is string => typeof s === "string" && s.trim() !== "").slice(0, limit) : [];
}

function count(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) && v >= 0 ? Math.floor(v) : 0;
}

/** A file's text, if it's a plain file no bigger than `max`; a symlink isn't followed. */
async function readPlain(file: string, max: number): Promise<string | null> {
  try {
    const fh = await fs.open(file, fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW);
    try {
      const st = await fh.stat();
      if (!st.isFile() || st.size > max) return null;
      return await fh.readFile("utf8");
    } finally {
      await fh.close();
    }
  } catch {
    return null;
  }
}

async function readJson(file: string): Promise<unknown> {
  const text = await readPlain(file, MAX_JSON_BYTES);
  try {
    return text === null ? null : JSON.parse(text);
  } catch {
    return null;
  }
}

function toNote(raw: unknown): StepNote | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const title = str(r.title).trim();
  return title ? { at: str(r.at), title, detail: str(r.detail) } : null;
}

function toFile(raw: unknown): StepFile | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const p = str(r.path);
  return p ? { path: p, added: count(r.added), removed: count(r.removed) } : null;
}

function toMade(raw: unknown): StepMade | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const name = str(r.name);
  if (!MADE_NAME.test(name) || !(path.extname(name).toLowerCase() in MADE_TYPES)) return null;
  return { name, caption: str(r.caption), image: IMAGE.has(path.extname(name).toLowerCase()) };
}

function toStep(raw: unknown, project: string, when: string): ProjectStep | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const status = STATUSES.find((s) => s === r.status);
  if (r.id !== `${project}/${when}` || !status) return null;
  const meta = r.meta && typeof r.meta === "object" ? (r.meta as Record<string, unknown>) : {};
  const list = <T,>(v: unknown, to: (x: unknown) => T | null, limit: number) =>
    Array.isArray(v) ? v.map(to).filter((x): x is T => x !== null).slice(0, limit) : [];
  const open = status === "ready" || status === "failed" || status === "working";
  return {
    id: r.id,
    created: str(r.created),
    updated: str(r.updated),
    status,
    summary: str(r.summary),
    asked: str(r.asked),
    runner: r.runner === "claude" || r.runner === "local" ? r.runner : "",
    step: str(r.step),
    why: str(r.why),
    did: str(r.did),
    found: str(r.found),
    couldnt: str(r.couldnt),
    next: str(r.next),
    made: list(r.made, toMade, 30),
    files: list(r.files, toFile, 200),
    branch: str(r.branch),
    base: str(r.base),
    worktree: open && str(r.worktree) ? displayPath(str(r.worktree)) : "",
    thread: list(r.thread, toNote, 50),
    error: str(r.error) || null,
    turns: typeof meta.turns === "number" ? count(meta.turns) : null,
  };
}

/** Where it stands, without the title and the date line the projects clone puts first. */
function splitStatus(text: string): { status: string; date: string } {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  if (lines[0]?.startsWith("# ")) lines.shift();
  let date = "";
  while (lines.length && !lines[0].trim()) lines.shift();
  const m = lines[0]?.match(/^_Where it stands, (\d{4}-\d{2}-\d{2})\._$/);
  if (m) {
    date = m[1];
    lines.shift();
  }
  return { status: lines.join("\n").trim(), date };
}

function toQueued(raw: unknown): QueuedStep | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const text = str(r.text).trim();
  return text && /^q-[0-9a-f]{12}$/.test(str(r.id)) ? { id: str(r.id), text, added: str(r.added) } : null;
}

async function readSteps(dir: string, project: string, job: Job | null): Promise<ProjectStep[]> {
  let names: string[] = [];
  try {
    names = (await fs.readdir(dir)).filter((n) => n.endsWith(".json") && WHEN.test(n.slice(0, -5)));
  } catch {
    // No steps yet.
  }
  names.sort().reverse(); // the name is when it began
  const found: ProjectStep[] = [];
  for (const name of names.slice(0, STEPS_SHOWN)) {
    const step = toStep(await readJson(path.join(dir, name)), project, name.slice(0, -5));
    if (!step) continue;
    // Still "working" with nothing taking it: the page's command for it ended without saying so,
    // or one started elsewhere (the night, a terminal) went quiet for longer than a step may take.
    const created = Date.parse(step.created);
    const ended =
      job !== null &&
      job.account === project &&
      job.state !== "running" &&
      Date.parse(job.started) <= created + 5000 &&
      created <= Date.parse(job.finished ?? "");
    const stale = Date.now() - (Date.parse(step.updated) || created) > STEP_MS;
    if (step.status === "working" && (ended || stale)) {
      step.status = "failed";
      step.error = (ended && job.state === "failed" && job.message) || "It didn't finish.";
    }
    found.push(step);
  }
  return found;
}

function toJob(job: Job | null): ProjectsJob | null {
  return job && { state: job.state, message: job.message, started: job.started, finished: job.finished, project: job.account };
}

/** Every project on the list, with where it stands, its queue and its newest steps, and how the jobs stand. */
export async function getProjects(): Promise<ProjectsResponse> {
  const vault = vaultPath();
  const root = path.join(vault, "clones", "projects");
  const job = latestJob("step");
  const listed = await readJson(path.join(root, "projects.json"));
  const raw = listed && typeof listed === "object" ? (listed as Record<string, unknown>).projects : null;
  const projects: WorkProject[] = [];
  const seen = new Set<string>();
  for (const p of Array.isArray(raw) ? raw : []) {
    if (!p || typeof p !== "object") continue;
    const r = p as Record<string, unknown>;
    const id = str(r.id);
    const name = str(r.name).trim();
    if (!PROJECT_ID.test(id) || !name || seen.has(id)) continue;
    seen.add(id);
    const folder = path.join(root, id);
    const { status, date } = splitStatus((await readPlain(path.join(folder, "status.md"), MAX_STATUS_BYTES)) ?? "");
    const queue = await readJson(path.join(folder, "queue.json"));
    const queued = queue && typeof queue === "object" ? (queue as Record<string, unknown>).steps : null;
    projects.push({
      id,
      name,
      about: str(r.about).trim(),
      paused: r.paused === true,
      repo: str(r.repo).trim() ? displayPath(path.resolve(expandHome(str(r.repo).trim()))) : "",
      data: strings(r.data, 10).map((d) => displayPath(path.resolve(expandHome(d.trim())))),
      status,
      statusDate: date,
      queue: Array.isArray(queued) ? queued.map(toQueued).filter((q): q is QueuedStep => q !== null) : [],
      steps: await readSteps(path.join(folder, "steps"), id, job),
    });
  }
  return { now: nowIso(), vault: await vaultInfo(vault), projects, job: toJob(job), deciding: toJob(latestJob("decide")) };
}

/** A figure or table a step made, to show on the page: its bytes and how to serve them, or null. */
export async function readMade(stepId: string, name: string): Promise<{ data: Buffer; type: string } | null> {
  const m = STEP_ID.exec(stepId);
  const type = MADE_TYPES[path.extname(name).toLowerCase()];
  if (!m || !MADE_NAME.test(name) || !type) return null;
  const file = path.join(vaultPath(), "clones", "projects", m[1], "steps", m[2], name);
  try {
    const fh = await fs.open(file, fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW);
    try {
      const st = await fh.stat();
      if (!st.isFile() || st.size > MAX_MADE_BYTES) return null;
      return { data: await fh.readFile(), type };
    } finally {
      await fh.close();
    }
  } catch {
    return null;
  }
}
