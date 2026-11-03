// Server side of the Jobs view. Import only from route handlers.
//
// The page reads clones/jobs/jobs.json as the jobs clone writes it, field by field, so nothing
// else in it reaches the page: not the records read, nor the excerpts of messages kept there for
// the model. Each job's status is the user's, the latest line for it in clones/jobs/status.jsonl,
// which the page appends to; the clone's suggestion of applied shows only while the job is new
// or interested, and goes once the user marks it not applied. A job's first step is a draft in
// clones/drafts, whose status comes from its own file.

import path from "node:path";

import type { Job, JobAction, JobPerson, JobSourceRef, JobStatus, JobsResponse, JobVerdict } from "./types";
import { JOB_ACTIONS, JOB_SOURCES } from "./types";
import { appendJsonl, draftStatus, DRAFT_ID, nowIso, readJsonFile, readJsonl, vaultInfo, vaultPath } from "./vault";

const MAX_JOBS = 400;
const MAX_JOBS_BYTES = 16 * 1024 * 1024;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const ID = /^[0-9a-f]{12}$/;
const VERDICTS: readonly JobVerdict[] = ["apply", "maybe", "skip"];

function record(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

function str(v: unknown, max = 600): string {
  return typeof v === "string" ? v.trim().slice(0, max) : "";
}

/** A link the page may open: http or https only. */
function web(v: unknown): string {
  const s = str(v, 2000);
  try {
    const u = new URL(s);
    return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : "";
  } catch {
    return "";
  }
}

export function isJobId(v: unknown): v is string {
  return typeof v === "string" && ID.test(v);
}

export function isJobAction(v: unknown): v is JobAction {
  return typeof v === "string" && (JOB_ACTIONS as readonly string[]).includes(v);
}

function toPerson(raw: unknown): JobPerson | null {
  const r = record(raw);
  const name = str(r?.name, 120);
  if (!r || !name) return null;
  return { name, how: str(r.how, 300), channel: str(r.channel, 40), role: r.role === "contact" ? "contact" : "known" };
}

function toSource(raw: unknown): JobSourceRef | null {
  const r = record(raw);
  const source = JOB_SOURCES.find((s) => s === r?.source);
  const label = str(r?.label, 400);
  if (!r || !source || !label) return null;
  return { source, label, ts: str(r.ts, 40), id: str(r.id, 400) };
}

function toJob(raw: unknown): (Omit<Job, "status" | "status_at" | "suggested" | "draft"> & { draftId: string | null; suggested: Job["suggested"] }) | null {
  const r = record(raw);
  const id = str(r?.id, 40);
  const role = str(r?.role, 200);
  if (!r || !ID.test(id) || !role) return null;
  const route = record(r.route);
  const cv = record(r.cv);
  const step = record(r.step);
  const suggested = record(r.suggested);
  const draftId = str(r.draft_id, 80);
  const deadline = str(r.deadline, 10);
  return {
    id,
    company: str(r.company, 200),
    role,
    place: str(r.place, 200),
    mode: str(r.mode, 20),
    pay: str(r.pay, 200),
    deadline: DAY.test(deadline) ? deadline : "",
    link: web(r.link),
    reply_link: web(r.reply_link),
    verdict: VERDICTS.find((v) => v === r.verdict) ?? null,
    why: str(r.why, 1200),
    rests_on: (Array.isArray(r.rests_on) ? r.rests_on : []).map((f) => str(f, 80)).filter(Boolean).slice(0, 6),
    route: route && str(route.kind, 20) ? { kind: str(route.kind, 20), why: str(route.why, 400) } : null,
    cv: cv && str(cv.name, 200) ? { name: str(cv.name, 200), kind: str(cv.kind, 40), why: str(cv.why, 300) } : null,
    people: (Array.isArray(r.people) ? r.people : []).slice(0, 4).map(toPerson).filter((p): p is JobPerson => p !== null),
    step: step && str(step.kind, 20) ? { kind: str(step.kind, 20), to: str(step.to, 120), channel: str(step.channel, 40) } : null,
    draftId: DRAFT_ID.test(draftId) ? draftId : null,
    errand: str(r.errand, 600),
    sources: (Array.isArray(r.sources) ? r.sources : []).slice(0, 20).map(toSource).filter((s): s is JobSourceRef => s !== null),
    first_seen: str(r.first_seen, 40),
    last_seen: str(r.last_seen, 40),
    suggested: suggested && str(suggested.why) ? { why: str(suggested.why), ts: str(suggested.ts, 40) } : null,
  };
}

/** The user's latest status of each job, and when they last set a suggestion of applied aside. */
async function marks(file: string): Promise<Map<string, { status: JobStatus; at: string | null; notApplied: string }>> {
  const found = new Map<string, { status: JobStatus; at: string | null; notApplied: string }>();
  for (const raw of await readJsonl(file)) {
    const r = record(raw);
    const id = str(r?.job_id, 40);
    const ts = str(r?.ts, 40);
    if (!r || !ID.test(id) || !ts || !isJobAction(r.action)) continue;
    const mark = found.get(id) ?? { status: "new" as JobStatus, at: null, notApplied: "" };
    if (r.action === "not_applied") {
      if (ts > mark.notApplied) mark.notApplied = ts;
    } else {
      mark.status = r.action;
      mark.at = ts;
    }
    found.set(id, mark);
  }
  return found;
}

/** Every job, as clones/jobs/jobs.json has them in order (apply first), with the user's status and each first step's draft folded in. */
export async function getJobs(): Promise<JobsResponse> {
  const vault = vaultPath();
  const dir = path.join(vault, "clones", "jobs");
  const doc = record(await readJsonFile(path.join(dir, "jobs.json"), MAX_JOBS_BYTES));
  const marked = await marks(path.join(dir, "status.jsonl"));
  const seen = new Set<string>();
  const jobs: Job[] = [];
  for (const raw of (Array.isArray(doc?.jobs) ? doc.jobs : []).slice(0, MAX_JOBS)) {
    const job = toJob(raw);
    if (!job || seen.has(job.id)) continue;
    seen.add(job.id);
    const { draftId, suggested, ...rest } = job;
    const mark = marked.get(job.id);
    const status = mark?.status ?? "new";
    const open = status === "new" || status === "interested";
    jobs.push({
      ...rest,
      status,
      status_at: mark?.at ?? null,
      suggested: open && suggested && suggested.ts > (mark?.notApplied ?? "") ? suggested : null,
      draft: draftId ? { id: draftId, status: await draftStatus(vault, draftId) } : null,
    });
  }
  const cvs = (Array.isArray(doc?.cvs) ? doc.cvs : [])
    .map(record)
    .map((c) => ({ name: str(c?.name, 200), kind: str(c?.kind, 40) }))
    .filter((c) => c.name)
    .slice(0, 4);
  return { now: nowIso(), vault: await vaultInfo(vault), generated: str(doc?.generated, 40) || null, cvs, jobs };
}

/** One line in clones/jobs/status.jsonl: the job's new status, or a suggestion of applied set aside. */
export async function appendJobStatus(jobId: string, action: JobAction) {
  const entry = { job_id: jobId, action, ts: nowIso() };
  await appendJsonl(["clones", "jobs", "status.jsonl"], entry);
  return entry;
}
