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

import { lastLine, NO_COMMAND, startJob, type Job } from "./connect";
import { isBranch, isRepoPath } from "./projects";
import type {
  ChangedFile,
  DiffOp,
  FileChanges,
  ManuscriptEdit,
  ManuscriptResponse,
  ManuscriptVersion,
  StepChangesResponse,
} from "./types";
import { proxenos } from "./vault";

const READ_MS = 60_000;
const MAX_OUTPUT = 32 * 1024 * 1024;
const VERSIONS = 200;

export type Read<T> = { data: T } | { error: string; status: number };

/** A version as the command takes one: a commit, or a branch. */
export function isRev(value: unknown): value is string {
  return isBranch(value);
}

/** The command's answer, parsed, or why there's none: what it said last, without its name. */
function run(args: string[]): Promise<Read<unknown>> {
  return proxenos().then(
    (cli) =>
      new Promise((resolve) => {
        if (!cli) return resolve({ error: NO_COMMAND, status: 500 });
        cli.exec(["project", "manuscript", ...args], { timeout: READ_MS, maxBuffer: MAX_OUTPUT }, (error, stdout, stderr) => {
          if (error) {
            const why = error.killed ? "It took too long." : lastLine(stderr) || lastLine(stdout) || "It failed.";
            return resolve({ error: why.replace(/^(manuscript|steps): /, ""), status: error.killed ? 504 : 400 });
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
