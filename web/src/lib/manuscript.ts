// Server side of a project's manuscript on the Projects page. Import only from route handlers.
//
// `proxenos project manuscript <id>` reads the project's code with git and answers in JSON: the
// manuscript, its versions, and one version's text with its changes since another; with --step,
// every file a step changed. Nothing in the user's checkout is read or touched. The answer is read
// field by field, so nothing else in it reaches the page.
//
// An edit the user saves goes to the same command with --edit, its text on the command's stdin,
// and runs as the job "decide", like an Accept: it commits the text on a new branch, made apart
// from the user's checkout, as a step waiting on them to accept or discard.
//
// Its Google Doc is `proxenos project gdocs <id>`: as kept in the vault, with nothing fetched; or,
// with an action, made in the user's own Drive (open, fresh), its changes brought back as a step
// waiting on them (pull), or its comments read again (comments). Those wait for the answer, which
// is short: one upload or export, the comments, and at most a commit.

import { latestJob, lastLine, NO_COMMAND, startJob, type Job } from "./connect";
import { isBranch, isRepoPath, isStepId } from "./projects";
import type {
  ChangedFile,
  DiffOp,
  DocComment,
  DocReply,
  FileChanges,
  ManuscriptDoc,
  ManuscriptDocPull,
  ManuscriptDocResponse,
  ManuscriptEdit,
  ManuscriptResponse,
  ManuscriptVersion,
  StepChangesResponse,
} from "./types";
import { proxenos } from "./vault";

const READ_MS = 60_000;
const DOC_MS = 3 * 60_000;
const COMMENTS = 1000;
const MAX_OUTPUT = 32 * 1024 * 1024;
const VERSIONS = 200;

export type Read<T> = { data: T } | { error: string; status: number };

/** A version as the command takes one: a commit, or a branch. */
export function isRev(value: unknown): value is string {
  return isBranch(value);
}

/** The command's answer, parsed, or why there's none: what it said last, without its name. */
function run(args: string[], what: "manuscript" | "gdocs" = "manuscript", timeout = READ_MS): Promise<Read<unknown>> {
  return proxenos().then(
    (cli) =>
      new Promise((resolve) => {
        if (!cli) return resolve({ error: NO_COMMAND, status: 500 });
        cli.exec(["project", what, ...args], { timeout, maxBuffer: MAX_OUTPUT }, (error, stdout, stderr) => {
          if (error) {
            const why = error.killed ? "It took too long." : lastLine(stderr) || lastLine(stdout) || "It failed.";
            return resolve({ error: why.replace(/^(manuscript|steps|gdocs): /, ""), status: error.killed ? 504 : 400 });
          }
          try {
            resolve({ data: JSON.parse(stdout) as unknown });
          } catch {
            resolve({ error: "The answer wasn't JSON.", status: 500 });
          }
        });
      }),
  );
}

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function count(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) && v >= 0 ? Math.floor(v) : 0;
}

function obj(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function toOp(raw: unknown): DiffOp | null {
  const r = obj(raw);
  return (r.op === "same" || r.op === "add" || r.op === "del") && typeof r.text === "string" ? { op: r.op, text: r.text } : null;
}

function toChanges(r: Record<string, unknown>): FileChanges {
  const prose = r.kind !== "code";
  return {
    kind: prose ? "prose" : "code",
    unit: prose ? "words" : "lines",
    text: str(r.text),
    ops: Array.isArray(r.ops) ? r.ops.map(toOp).filter((o): o is DiffOp => o !== null) : [],
    added: count(r.added),
    removed: count(r.removed),
    binary: r.binary === true,
    truncated: r.truncated === true,
  };
}

function toVersion(raw: unknown): ManuscriptVersion | null {
  const r = obj(raw);
  const commit = str(r.commit);
  if (!/^[0-9a-f]{40,64}$/.test(commit)) return null;
  return {
    commit,
    short: str(r.short) || commit.slice(0, 7),
    date: str(r.date),
    author: str(r.author),
    subject: str(r.subject),
    branch: str(r.branch),
    proxenos: r.proxenos === true,
    edit: r.edit === true,
    step: typeof r.step === "string" ? r.step : null,
    path: str(r.path),
  };
}

/** The manuscript of a project, one version of it and its changes since another. */
export async function readManuscript(project: string, base?: string, head?: string): Promise<Read<ManuscriptResponse>> {
  const args = [project, ...(base ? ["--base", base] : []), ...(head ? ["--head", head] : [])];
  const answer = await run(args);
  if ("error" in answer) return answer;
  const r = obj(answer.data);
  const m = obj(r.manuscript);
  const found = isRepoPath(m.path) && isBranch(m.branch) ? { path: m.path, branch: m.branch, named: m.named === true } : null;
  return {
    data: {
      project,
      manuscript: found,
      why: str(r.why),
      versions: Array.isArray(r.versions) ? r.versions.slice(0, VERSIONS).map(toVersion).filter((v): v is ManuscriptVersion => v !== null) : [],
      tip: str(r.tip),
      base: str(r.base),
      head: str(r.head),
      editable: found !== null && r.editable === true,
      ...toChanges(r),
    },
  };
}

/** Every file a step changed, from where it started to its branch. */
export async function readStepChanges(project: string, step: string): Promise<Read<StepChangesResponse>> {
  const answer = await run([project, "--step", step]);
  if ("error" in answer) return answer;
  const r = obj(answer.data);
  const files: ChangedFile[] = [];
  for (const raw of Array.isArray(r.files) ? r.files : []) {
    const f = obj(raw);
    if (typeof f.path === "string" && f.path) files.push({ path: f.path, ...toChanges(f) });
  }
  return {
    data: { project, step, branch: str(r.branch), base: str(r.base), files, truncated: r.truncated === true },
  };
}

/** Save the user's text as a step waiting on them. Null when another decision is still going. */
export function startEdit(project: string, edit: ManuscriptEdit): Promise<Job | null> {
  return startJob("decide", ["project", "manuscript", project, "--edit"], null, JSON.stringify(edit) + "\n");
}

// ── Its Google Doc ──────────────────────────────────────────────────────────

export const DOC_ACTIONS = ["open", "fresh", "pull", "comments"] as const;
export type DocAction = (typeof DOC_ACTIONS)[number];

// On globalThis, so every route sees which projects' docs are busy.
const shared = globalThis as typeof globalThis & { __proxenosDocs?: Set<string> };
const BUSY = (shared.__proxenosDocs ??= new Set<string>());

function toReply(raw: unknown): DocReply {
  const r = obj(raw);
  return { author: str(r.author) || "Someone", content: str(r.content), created: str(r.created) };
}

function toComment(raw: unknown): DocComment | null {
  const r = obj(raw);
  if (!str(r.content) && !Array.isArray(r.replies)) return null;
  return {
    id: str(r.id),
    author: str(r.author) || "Someone",
    content: str(r.content),
    quoted: str(r.quoted),
    resolved: r.resolved === true,
    created: str(r.created),
    replies: Array.isArray(r.replies) ? r.replies.map(toReply) : [],
  };
}

/** The doc's record, if its link is a Google Docs one: the page opens it in a new tab. */
function toDoc(raw: unknown): ManuscriptDoc | null {
  const r = obj(raw);
  const link = str(r.link);
  if (!link.startsWith("https://docs.google.com/")) return null;
  return {
    link,
    title: str(r.title),
    account: str(r.account),
    address: str(r.address),
    path: str(r.path),
    branch: str(r.branch),
    commit: str(r.commit),
    at: str(r.at),
    pulled: typeof r.pulled === "string" ? r.pulled : null,
    step: isStepId(r.step) ? r.step : null,
  };
}

function toDocState(project: string, r: Record<string, unknown>): ManuscriptDocResponse {
  const accounts = Array.isArray(r.accounts) ? r.accounts.map(obj) : [];
  return {
    project,
    accounts: accounts.map((a) => ({ name: str(a.name), address: str(a.address) })).filter((a) => a.name),
    doc: toDoc(r.doc),
    comments: Array.isArray(r.comments)
      ? r.comments.slice(0, COMMENTS).map(toComment).filter((c): c is DocComment => c !== null)
      : [],
    commentsRead: typeof r.comments_read === "string" ? r.comments_read : null,
  };
}

/** The project's Google Doc and its comments as kept in the vault. Nothing is fetched. */
export async function readDoc(project: string): Promise<Read<ManuscriptDocResponse>> {
  const answer = await run([project], "gdocs");
  return "error" in answer ? answer : { data: toDocState(project, obj(answer.data)) };
}

/**
 * Make the doc (open: the first time, else its link; fresh: a new one), bring back its changes
 * as a step waiting on the user (pull), or read its comments again. One at a time for a project,
 * and a pull not while a decision is going, since both commit.
 */
export async function actOnDoc(project: string, action: DocAction): Promise<Read<ManuscriptDocResponse | ManuscriptDocPull>> {
  if (BUSY.has(project)) return { error: "The last one is still going.", status: 409 };
  if (action === "pull" && latestJob("decide")?.state === "running") {
    return { error: "Wait for the decision that's going to finish.", status: 409 };
  }
  BUSY.add(project);
  try {
    const answer = await run([project, action], "gdocs", DOC_MS);
    if ("error" in answer) return answer;
    const r = obj(answer.data);
    const state = toDocState(project, r);
    if (action !== "pull") return { data: state };
    return { data: { ...state, changed: r.changed === true, step: isStepId(r.step) ? r.step : null, said: str(r.said) } };
  } finally {
    BUSY.delete(project);
  }
}
