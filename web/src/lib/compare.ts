// Server side of Settings' "Which writes like you?". Import only from route handlers.
//
// Everything comes from `proxenos compare results [ROUND]`, which keeps each reply blind until the
// reader has picked: which model wrote A or B, how close each came and what they sent never reach
// the page before that. Its answer is read field by field, so nothing else in it does either. A
// round is drafted by `proxenos compare start` as the job "compare", one at a time, and the page
// follows it through GET /api/compare, since the command writes the round after every draft. A
// pick runs `proxenos compare pick` and answers with the round as it then stands. Nothing here
// sends anything to anyone.

import { ASK_MS, lastLine, latestJob, NO_COMMAND, startJob, stopJob, type Job } from "./connect";
import {
  COMPARE_MAX_ROUND,
  COMPARE_PICKS,
  MODEL_WHERES,
  type CompareFared,
  type CompareItem,
  type CompareJob,
  type CompareMessage,
  type CompareModel,
  type ComparePick,
  type CompareResponse,
  type CompareResults,
  type CompareRound,
  type CompareRoundListed,
  type CompareSetUp,
  type ModelWhere,
} from "./types";
import { nowIso, proxenos, vaultInfo, vaultPath } from "./vault";

const RESULTS_MS = 60_000;
const MAX_OUTPUT = 16 * 1024 * 1024;
const ROUND_ID = /^\d{8}T\d{6}Z$/;
// A model's name as Settings takes PROXENOS_MODEL, which "voice:" and a voice model's setting also
// fit; the command checks each kind exactly.
const MODEL = /^[\w.:/-]{1,100}$/;
const MAX_TEXT = 4000;
const MAX_MESSAGES = 60;
const MAX_ITEMS = COMPARE_MAX_ROUND;
const STATUSES: readonly CompareRound["status"][] = ["drafting", "ready", "failed", "stopped"];

export function isRoundId(value: unknown): value is string {
  return typeof value === "string" && ROUND_ID.test(value);
}

/** A model a round may be asked for, or null. */
export function parseModel(value: unknown): string | null {
  const model = typeof value === "string" ? value.trim() : "";
  return MODEL.test(model) && !model.startsWith("-") ? model : null;
}

export function isPick(value: unknown): value is ComparePick {
  return COMPARE_PICKS.some((p) => p === value);
}

// ── Reading the command's answer ────────────────────────────────────────────

function rec(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function list(v: unknown, limit: number): unknown[] {
  return Array.isArray(v) ? v.slice(0, limit) : [];
}

function str(v: unknown, limit = MAX_TEXT): string {
  return typeof v === "string" ? v.slice(0, limit) : "";
}

function count(v: unknown): number {
  return typeof v === "number" && Number.isInteger(v) && v >= 0 ? v : 0;
}

/** A share from 0 to 1, or null. */
function share(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 1 ? v : null;
}

function where(v: unknown): ModelWhere {
  return MODEL_WHERES.find((w) => w === v) ?? "Anthropic";
}

function toMessage(raw: unknown): CompareMessage | null {
  const r = rec(raw);
  const text = str(r.text);
  if (!text || !str(r.ts)) return null;
  return { ts: str(r.ts, 40), mine: r.mine === true, sender: str(r.sender, 200) || null, text };
}

function messages(v: unknown): CompareMessage[] {
  return list(v, MAX_MESSAGES).flatMap((m) => toMessage(m) ?? []);
}

function toItem(raw: unknown): CompareItem | null {
  const r = rec(raw);
  const n = count(r.n);
  if (!n) return null;
  const pick = isPick(r.pick) ? r.pick : null;
  const state = r.state === "ready" || r.state === "failed" ? r.state : "drafting";
  const ready = state === "ready" && typeof r.a === "string" && typeof r.b === "string";
  return {
    n,
    source: str(r.source, 40),
    name: str(r.name, 200) || "them",
    replied: str(r.replied, 40),
    recent: messages(r.recent),
    waiting: messages(r.waiting),
    state: ready ? "ready" : state === "ready" ? "drafting" : state,
    a: ready ? str(r.a) : null,
    b: ready ? str(r.b) : null,
    pick,
    picked: pick ? str(r.picked, 40) || null : null,
    // Only once picked: the command says nothing of which model wrote which before that.
    revealed:
      pick && typeof r.a_model === "string" && typeof r.b_model === "string"
        ? {
            a: str(r.a_model, 120),
            b: str(r.b_model, 120),
            aCloseness: share(r.a_closeness),
            bCloseness: share(r.b_closeness),
            sent: str(r.sent),
          }
        : null,
  };
}

function toFared(raw: unknown): CompareFared | null {
  const r = rec(raw);
  const name = str(r.name, 120);
  if (!name) return null;
  return {
    name,
    label: str(r.label, 120) || name,
    where: where(r.where),
    won: count(r.won),
    share: share(r.share),
    low: share(r.low),
    high: share(r.high),
    closeness: share(r.closeness),
    drafted: count(r.drafted),
    failed: count(r.failed),
  };
}

function toResults(raw: unknown): CompareResults | null {
  const r = rec(raw);
  const models = list(r.models, 2).flatMap((m) => toFared(m) ?? []);
  if (models.length !== 2) return null;
  return { picks: count(r.picks), both: count(r.both), neither: count(r.neither), models, note: str(r.note, 300) };
}

function toModel(raw: unknown): CompareModel | null {
  const r = rec(raw);
  const name = str(r.name, 120);
  return name ? { name, label: str(r.label, 120) || name, where: where(r.where) } : null;
}

function toRound(raw: unknown): CompareRound | null {
  const r = rec(raw);
  const models = list(r.models, 2).flatMap((m) => toModel(m) ?? []);
  if (!isRoundId(r.id) || models.length !== 2) return null;
  return {
    id: r.id,
    started: str(r.started, 40),
    updated: str(r.updated, 40),
    status: STATUSES.find((s) => s === r.status) ?? "failed",
    error: str(r.error, 300) || null,
    models,
    n: count(r.n),
    drafted: count(r.drafted),
  };
}

function toListed(raw: unknown): CompareRoundListed | null {
  const r = rec(raw);
  if (!isRoundId(r.id)) return null;
  return {
    id: r.id,
    started: str(r.started, 40),
    status: STATUSES.find((s) => s === r.status) ?? "failed",
    models: list(r.models, 2).map((m) => str(m, 120)),
    n: count(r.n),
    picked: count(r.picked),
  };
}

function toSetUp(raw: unknown): CompareSetUp | null {
  const r = rec(raw);
  const drafting = str(r.drafting, 120);
  if (!drafting) return null;
  return { drafting, hosted: str(r.hosted, 120), key: r.key === true, voice: str(r.voice, 120) || null };
}

function toJob(job: Job | null): CompareJob | null {
  return job && { state: job.state, message: job.message, started: job.started, finished: job.finished };
}

/**
 * The round as it stands: one the file says is still being drafted, with nothing drafting it any more, has stopped.
 * That's when the page's own run of it ended, or, for one started elsewhere, when it hasn't moved for as long as a
 * draft may take.
 */
function settled(round: CompareRound | null, job: CompareJob | null): CompareRound | null {
  if (!round || round.status !== "drafting" || job?.state === "running") return round;
  const ours = job !== null && Date.parse(job.started) <= Date.parse(round.started) + 5000;
  const idle = Date.now() - (Date.parse(round.updated) || 0) > ASK_MS;
  if (!ours && !idle) return round;
  return { ...round, status: "stopped", error: (ours && job.state !== "done" && job.message) || "It stopped before it finished." };
}

type Ran = { view: Record<string, unknown> } | { error: string };

async function run(args: string[]): Promise<Ran> {
  const cli = await proxenos();
  if (!cli) return { error: NO_COMMAND };
  return new Promise((resolve) => {
    cli.exec(["compare", ...args], { timeout: RESULTS_MS, maxBuffer: MAX_OUTPUT }, (error, stdout, stderr) => {
      if (error) {
        resolve({ error: lastLine(stderr) || (error.killed ? "It took too long." : "It failed.") });
        return;
      }
      try {
        resolve({ view: rec(JSON.parse(stdout)) });
      } catch {
        resolve({ error: "proxenos compare gave an answer this page can't read." });
      }
    });
  });
}

async function answer(ran: Ran): Promise<CompareResponse> {
  const job = toJob(latestJob("compare"));
  const base = { now: nowIso(), vault: await vaultInfo(vaultPath()), job };
  if ("error" in ran) {
    return { ...base, round: null, rounds: [], results: null, pooled: null, items: [], setUp: null, error: ran.error };
  }
  const v = ran.view;
  const pooled = toResults(v.pooled);
  return {
    ...base,
    round: settled(toRound(v.round), job),
    rounds: list(v.rounds, 50).flatMap((r) => toListed(r) ?? []),
    results: toResults(v.results),
    pooled: pooled && { ...pooled, rounds: count(rec(v.pooled).rounds) },
    items: list(v.items, MAX_ITEMS).flatMap((i) => toItem(i) ?? []),
    setUp: toSetUp(v.set_up),
    error: null,
  };
}

// ── What the page asks for ──────────────────────────────────────────────────

/** A round, the newest unless named, blind where it hasn't been picked, and how the job stands. */
export async function getCompare(round: string | null): Promise<CompareResponse> {
  return answer(await run(["results", ...(round ? [round] : [])]));
}

/** Pick for one reply of a round; a new pick replaces the last. The round as it then stands. */
export async function pickCompare(round: string, item: number, pick: ComparePick): Promise<CompareResponse> {
  return answer(await run(["pick", round, String(item), pick]));
}

/** Draft a new round in the background: `model` against the drafting model set up. Null when one is being drafted. */
export async function startCompare(model: string, n: number): Promise<CompareJob | null> {
  // "--model=" so nothing in the name is taken for an option.
  return toJob(await startJob("compare", ["compare", "start", `--model=${model}`, "-n", String(n)], model));
}

/** Stop the round being drafted. Whether one was. */
export function stopCompare(): boolean {
  return stopJob("compare");
}
