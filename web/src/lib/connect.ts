// Server side of the Connect view. Import only from route handlers.
//
// Which sources are connected comes from `proxenos connect`, which reports names, addresses,
// handles and dates, never a secret. Its answer is read field by field, so nothing else in it
// reaches the page. A sign-in (`proxenos auth gmail`, `microsoft` or `gcalendar`), a read of
// WhatsApp (`proxenos ingest whatsapp`) and a Beeper token (`proxenos auth beeper`) run in the
// background, one of each at a time, and the page follows them through connectJobs(). A job tells
// the page only its command's last line, with anything that looks like a token blanked. The one
// secret the page sends is Beeper's: it goes to the command on its stdin and nowhere else.
//
// The Ask page's `proxenos ask` runs through the same jobs, as the kind "ask": one at a time,
// its question on stdin, its last line the id of the ask. connectJobs() leaves it out; askJobs()
// reports them. So do the Errands page's errands ("errand") and their Sends and Drops ("send").

import { execFile, type ChildProcess } from "node:child_process";

import { isAddress } from "./actions";
import { NO_STORE, readLocalJson } from "./guard";
import type {
  ConnectHow,
  ConnectJob,
  ConnectResponse,
  ConnectSource,
  JobKind,
  MailAccount,
  PhoneInfo,
  SignInKind,
} from "./types";
import { CONNECT_JOB_KINDS } from "./types";
import { nowIso, proxenosBin, REPO_ROOT, vaultInfo, vaultPath } from "./vault";

const STATUS_MS = 30_000;
// A sign-in waits up to five minutes for the browser; a first read of WhatsApp can take a while;
// checking a Beeper token is one request; a question to a local model can take a quarter of an hour,
// and so can an errand; a Send is one email or chat message.
export const ASK_MS = 15 * 60_000;
const JOB_MS: Record<JobKind, number> = {
  gmail: 6 * 60_000,
  microsoft: 6 * 60_000,
  gcalendar: 6 * 60_000,
  whatsapp: 15 * 60_000,
  beeper: 60_000,
  ask: ASK_MS,
  errand: ASK_MS,
  send: 3 * 60_000,
};
const MAX_OUTPUT = 1024 * 1024;
const MAX_MESSAGE = 300;
export const NO_COMMAND = "Couldn't find the proxenos command. Set PROXENOS_BIN in .env.";

// Shapes a secret could take in a command's output: a sign-in as .env keeps it, Slack,
// Anthropic, Google and Microsoft tokens (an access token is a JWT; a refresh token starts M.C
// for a personal account and 0.A for a work one), a bearer header, and any long run of letters
// and digits.
const SECRET_SHAPES = [
  /oauth:\S*/gi,
  /\bxox[a-z]-[\w-]+/gi,
  /\bsk-ant-[\w-]+/gi,
  /\bya29\.[\w.-]+/g,
  /\b1\/\/[\w-]+/g,
  /\beyJ[\w-]*\.[\w.-]+/g,
  /\bM\.C\d+_[\w.!*$-]+/g,
  /\b0\.A[\w.!*$-]{20,}/g,
  /\bbearer\s+\S+/gi,
  /\b(?=[\w-]*\d)(?=[\w-]*[a-z])[\w-]{32,}/gi,
];

/** The last non-empty line of a command's output, with anything that looks like a secret blanked. */
export function lastLine(text: string): string {
  let line = text.split("\n").map((l) => l.trim()).filter(Boolean).pop() ?? "";
  for (const shape of SECRET_SHAPES) line = line.replace(shape, "[hidden]");
  return line.length > MAX_MESSAGE ? line.slice(0, MAX_MESSAGE - 1) + "…" : line;
}

// ── Sources ─────────────────────────────────────────────────────────────────

const HOWS: readonly ConnectHow[] = ["live", "download", "folder"];

function str(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

function toAccount(raw: unknown): MailAccount | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const name = str(r.name);
  const address = str(r.address);
  if (!name || !address) return null;
  const signIn = r.sign_in === "google" || r.sign_in === "microsoft" ? r.sign_in : "app_password";
  return { name, address, signIn, lastRead: str(r.last_read) };
}

function toSource(raw: unknown): ConnectSource | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const id = str(r.id);
  const how = HOWS.find((h) => h === r.how);
  if (!id || !how) return null;
  return {
    id,
    how,
    connected: r.connected === true,
    lastRead: str(r.last_read),
    problem: str(r.problem),
    detail: str(r.detail),
    accounts: Array.isArray(r.accounts) ? r.accounts.map(toAccount).filter((a): a is MailAccount => a !== null) : [],
    workspaces: Array.isArray(r.workspaces) ? r.workspaces.filter((w): w is string => typeof w === "string") : [],
  };
}

const NO_PHONE: PhoneInfo = { address: null, login: null };

/** Where the phone reaches this page. The address is a link on the page, so only an https one passes. */
function toPhone(raw: unknown): PhoneInfo {
  if (!raw || typeof raw !== "object") return NO_PHONE;
  const r = raw as Record<string, unknown>;
  let address = str(r.address);
  try {
    if (address && new URL(address).protocol !== "https:") address = null;
  } catch {
    address = null;
  }
  return { address, login: str(r.login) };
}

/** Every source and whether it's connected, from `proxenos connect`, and the jobs as they stand. */
export async function getConnect(): Promise<ConnectResponse> {
  const vault = vaultPath();
  const base = { now: nowIso(), vault: await vaultInfo(vault), jobs: connectJobs(), phone: NO_PHONE };
  const bin = await proxenosBin();
  if (!bin) return { ...base, sources: [], error: NO_COMMAND };
  return new Promise((resolve) => {
    execFile(bin, ["connect"], { cwd: REPO_ROOT, timeout: STATUS_MS, maxBuffer: MAX_OUTPUT }, (error, stdout, stderr) => {
      if (error) {
        const why = lastLine(stderr) || (error.killed ? "it took too long" : "it failed");
        resolve({ ...base, sources: [], error: `proxenos connect didn't answer: ${why}` });
        return;
      }
      let sources: unknown;
      let phone: unknown;
      try {
        ({ sources, phone } = JSON.parse(stdout) as { sources?: unknown; phone?: unknown });
      } catch {
        sources = null;
      }
      if (!Array.isArray(sources)) {
        resolve({ ...base, sources: [], error: "proxenos connect gave an answer this page can't read." });
        return;
      }
      resolve({
        ...base,
        sources: sources.map(toSource).filter((s): s is ConnectSource => s !== null),
        phone: toPhone(phone),
        error: null,
      });
    });
  });
}

// ── Jobs ────────────────────────────────────────────────────────────────────

/** A job of any kind: a ConnectJob, or the Ask page's. */
export type Job = Omit<ConnectJob, "kind"> & { kind: JobKind };

interface Running {
  job: Job;
  child: ChildProcess | null;
  stopping: boolean;
}

// On globalThis, so every route sees the same jobs and a reload of this module in development
// doesn't lose track of a command that's still running.
const shared = globalThis as typeof globalThis & {
  __proxenosConnectJobs?: Map<JobKind, Running>;
  __proxenosAskJobs?: Running[];
};
const JOBS = (shared.__proxenosConnectJobs ??= new Map<JobKind, Running>());
/** The last few asks' jobs, newest first, so an ask that never wrote its end can still be told why. */
const ASKS = (shared.__proxenosAskJobs ??= []);
const ASKS_KEPT = 20;

/** The latest job of each kind the Connect page starts: running, or how it ended. */
export function connectJobs(): ConnectJob[] {
  return CONNECT_JOB_KINDS.flatMap((kind) => {
    const entry = JOBS.get(kind);
    return entry ? [{ ...entry.job, kind }] : [];
  });
}

/** The latest job of this kind: running, or how it ended. Null before the first since the server started. */
export function latestJob(kind: JobKind): Job | null {
  const entry = JOBS.get(kind);
  return entry ? { ...entry.job } : null;
}

/** The latest asks' jobs, newest first: running, or how they ended. Empty before the first since the server started. */
export function askJobs(): Job[] {
  return ASKS.map((entry) => ({ ...entry.job }));
}

/**
 * Run `proxenos <args>` in the background as the job of this kind. Resolves with the job, or
 * null when one of this kind is already running. A secret for the command goes in `stdin`, never
 * in `args`, which any process on the machine can read; if the command repeats it, it's blanked.
 * (An ask's question goes the same way, for the same reason; it is never echoed back either.)
 */
export async function startJob(
  kind: JobKind,
  args: string[],
  account: string | null = null,
  stdin: string | null = null,
): Promise<Job | null> {
  if (JOBS.get(kind)?.job.state === "running") return null;
  const entry: Running = {
    job: { kind, state: "running", message: "", account, started: nowIso(), finished: null },
    child: null,
    stopping: false,
  };
  // Claimed before anything is awaited, so a second click can't start a second one.
  JOBS.set(kind, entry);
  if (kind === "ask") ASKS.splice(0, ASKS.length, entry, ...ASKS.slice(0, ASKS_KEPT - 1));
  const finish = (state: Job["state"], message: string) => {
    entry.job = { ...entry.job, state, message, finished: nowIso() };
    entry.child = null;
  };

  const secret = stdin?.trim() ?? "";
  const hide = (text: string) => (secret ? text.split(secret).join("[hidden]") : text);

  const bin = await proxenosBin();
  if (!bin) finish("failed", NO_COMMAND);
  else if (entry.stopping) finish("stopped", "Stopped.");
  else {
    entry.child = execFile(bin, args, { cwd: REPO_ROOT, timeout: JOB_MS[kind], maxBuffer: MAX_OUTPUT }, (error, stdout, stderr) => {
      if (entry.stopping) finish("stopped", "Stopped.");
      else if (!error) finish("done", lastLine(hide(stdout)));
      else if (error.killed) finish("failed", "It took too long and was stopped.");
      else finish("failed", lastLine(hide(stderr)) || lastLine(hide(stdout)) || "It failed.");
    });
    if (stdin !== null) {
      // The command may exit without reading it all; that's reported by how it ends, not here.
      entry.child.stdin?.on("error", () => {});
      entry.child.stdin?.end(stdin);
    }
  }
  return { ...entry.job };
}

/** Stop the running job of this kind. Whether there was one. */
export function stopJob(kind: JobKind): boolean {
  const entry = JOBS.get(kind);
  if (!entry || entry.job.state !== "running") return false;
  entry.stopping = true;
  entry.child?.kill("SIGTERM");
  return true;
}

// ── Sign-ins ────────────────────────────────────────────────────────────────

/** <KIND>_<NAME>: a short name for the account. */
const ACCOUNT_NAME = /^[A-Za-z0-9_]{1,32}$/;

/**
 * A sign-in route's whole answer: POST {name, address} starts `proxenos auth KIND NAME ADDRESS`,
 * which opens the service's consent page in the browser and saves the token where Proxenos keeps
 * secrets. The request must pass readLocalJson (a loopback host, the same origin, a JSON body, so
 * no other site and no form post). Answers at once; the page follows the sign-in through
 * /api/connect/jobs.
 */
export async function startSignIn(req: Request, kind: SignInKind): Promise<Response> {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { name, address } = parsed.body;
  if (typeof name !== "string" || !ACCOUNT_NAME.test(name) || (kind === "microsoft" && name.toLowerCase() === "client_id")) {
    return Response.json({ error: "Name the account with letters, digits or _, e.g. personal." }, { status: 400 });
  }
  if (typeof address !== "string" || !isAddress(address)) {
    return Response.json({ error: "That isn't an email address." }, { status: 400 });
  }
  // "--" so nothing in them is taken for an option.
  const job = await startJob(kind, ["auth", kind, "--", name, address], address);
  if (!job) return Response.json({ error: "A sign-in is already waiting in the browser." }, { status: 409 });
  return Response.json({ job }, { status: 202, headers: NO_STORE });
}
