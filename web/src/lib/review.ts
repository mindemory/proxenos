// Server side of a paper's peer review on the Projects page. Import only from route handlers.
//
// `proxenos review <id> --rounds N` reviews the project's manuscript in rounds and keeps each
// review in clones/projects/<id>/reviews/: <when>.json, its rounds, reviewers and concerns, and
// <when>/round-<n>/ with each reviewer's report, the plan and the response letter, in markdown.
// The page reads those field by field, so nothing else in them reaches it. A review runs as the
// job "review", one at a time, for hours at most; the revision it makes is the project's steps,
// which the Projects page shows and the user accepts or discards as any other.

import { promises as fs } from "node:fs";
import path from "node:path";

import { latestJob, REVIEW_MS, startJob, type Job } from "./connect";
import { isStepId, readJson, readPlain, toJob, toNote } from "./projects";
import {
  REVIEW_ROUNDS_MAX,
  type ConcernStatus,
  type ReviewConcern,
  type ReviewReport,
  type ReviewRound,
  type ReviewRun,
  type ReviewsResponse,
  type ReviewStatus,
} from "./types";
import { nowIso, vaultPath } from "./vault";

const WHEN = /^\d{8}-\d{6}$/;
const CONCERN = /^R\d-[Mm]\d{1,3}$/;
const RUNS_SHOWN = 5;
const MAX_TEXT_BYTES = 512 * 1024;
const STATUSES: readonly ReviewStatus[] = ["working", "done", "stopped", "failed"];
const CONCERN_STATUSES: readonly ConcernStatus[] = ["open", "resolved", "partly resolved", "not resolved"];

/** How many rounds a review may be asked for. */
export function isRounds(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= REVIEW_ROUNDS_MAX;
}

/** Review the project's manuscript, for up to `rounds` rounds. Null when a review is already going. */
export function startReview(project: string, rounds: number): Promise<Job | null> {
  return startJob("review", ["review", project, "--rounds", String(rounds)], project);
}

function str(v: unknown, max = 4000): string {
  return typeof v === "string" ? v.slice(0, max) : "";
}

function num(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) && v >= 0 ? Math.floor(v) : 0;
}

function rec(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function list(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

async function text(file: string): Promise<string> {
  return (await readPlain(file, MAX_TEXT_BYTES)) ?? "";
}

async function toRound(raw: unknown, folder: string): Promise<ReviewRound | null> {
  const r = rec(raw);
  const n = num(r.n);
  if (!n) return null;
  const dir = path.join(folder, `round-${n}`);
  const reviews: ReviewReport[] = [];
  for (const item of list(r.reviews).slice(0, 4)) {
    const s = rec(item);
    const who = num(s.n);
    if (!who) continue;
    reviews.push({
      n: who,
      recommendation: str(s.recommendation, 40),
      score: typeof s.score === "number" ? num(s.score) : null,
      confidence: typeof s.confidence === "number" ? num(s.confidence) : null,
      major: num(s.major),
      minor: num(s.minor),
      resolved: num(s.resolved),
      partly: num(s.partly),
      unresolved: num(s.unresolved),
      dropped: num(s.dropped),
      takenOut: num(s.taken_out),
      text: await text(path.join(dir, `reviewer-${who}.md`)),
    });
  }
  const reviewed = rec(r.reviewed);
  const plan = rec(r.plan);
  return {
    n,
    status: str(r.status, 40),
    branch: str(reviewed.branch, 200),
    commit: str(reviewed.commit, 40),
    reviews,
    openMajor: num(r.open_major),
    openMinor: num(r.open_minor),
    plan: { text: num(plan.text), analysis: num(plan.analysis), later: num(plan.later), decline: num(plan.decline) },
    planText: Object.keys(plan).length ? await text(path.join(dir, "plan.md")) : "",
    response: r.response === true ? await text(path.join(dir, "response.md")) : "",
    steps: list(r.steps).filter(isStepId).slice(0, 10),
    error: str(r.error, 400),
  };
}

function toConcern(id: string, raw: unknown): ReviewConcern | null {
  const c = rec(raw);
  const status = CONCERN_STATUSES.find((s) => s === c.status);
  if (!CONCERN.test(id) || !status) return null;
  return {
    id,
    reviewer: num(c.reviewer),
    kind: c.kind === "major" ? "major" : "minor",
    round: num(c.round),
    title: str(c.title, 300),
    status,
    history: list(c.history)
      .map(rec)
      .map((h) => ({ round: num(h.round), status: str(h.status, 40) }))
      .slice(0, 10),
  };
}

async function toRun(raw: unknown, project: string, when: string, job: Job | null): Promise<ReviewRun | null> {
  const r = rec(raw);
  let status = STATUSES.find((s) => s === r.status);
  if (r.id !== `${project}/${when}` || !status) return null;
  const folder = path.join(vaultPath(), "clones", "projects", project, "reviews", when);
  const rounds: ReviewRound[] = [];
  for (const item of list(r.rounds).slice(0, REVIEW_ROUNDS_MAX)) {
    const round = await toRound(item, folder);
    if (round) rounds.push(round);
  }
  const thread = list(r.thread);
  const manuscript = rec(r.manuscript);
  let error = str(r.error, 400);
  // Still "working" with nothing running it: the page's job ended without saying so, or one started
  // elsewhere went quiet for longer than a review may take.
  const created = Date.parse(str(r.created));
  const ended =
    job !== null && job.account === project && job.state !== "running" && Date.parse(job.started) <= created + 5000;
  const stale = Date.now() - (Date.parse(str(r.updated)) || created) > REVIEW_MS;
  if (status === "working" && (ended || stale)) {
    status = "failed";
    error = (ended && job.state === "failed" && job.message) || "It didn't finish.";
  }
  return {
    id: r.id,
    created: str(r.created, 40),
    updated: str(r.updated, 40),
    status,
    summary: str(r.summary, 600),
    error,
    model: str(r.model, 80),
    roundsMax: num(r.rounds_max),
    manuscript: { path: str(manuscript.path, 300), branch: str(manuscript.branch, 200) },
    field: str(r.field, 200),
    venue: str(r.venue, 200),
    reviewers: list(r.reviewers)
      .map(rec)
      .filter((v) => num(v.n))
      .map((v) => ({ n: num(v.n), lens: str(v.lens, 120), expertise: str(v.expertise, 600) }))
      .slice(0, 4),
    rounds,
    concerns: Object.entries(rec(r.concerns))
      .map(([id, c]) => toConcern(id, c))
      .filter((c): c is ReviewConcern => c !== null)
      .slice(0, 300),
    latest: thread.length ? toNote(thread[thread.length - 1]) : null,
  };
}

/** The project's reviews, newest first, and how the review job stands. */
export async function getReviews(project: string): Promise<ReviewsResponse> {
  const job = latestJob("review");
  const dir = path.join(vaultPath(), "clones", "projects", project, "reviews");
  let names: string[] = [];
  try {
    names = (await fs.readdir(dir)).filter((n) => n.endsWith(".json") && WHEN.test(n.slice(0, -5)));
  } catch {
    // No review yet.
  }
  names.sort().reverse(); // the name is when it began
  const runs: ReviewRun[] = [];
  for (const name of names.slice(0, RUNS_SHOWN)) {
    const run = await toRun(await readJson(path.join(dir, name)), project, name.slice(0, -5), job);
    if (run) runs.push(run);
  }
  const mine = job && job.account === project ? job : null;
  return { now: nowIso(), project, runs, job: toJob(mine) };
}
