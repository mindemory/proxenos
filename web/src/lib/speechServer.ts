// Server side of Listen's voices made on this Mac (proxenos.speech). Import only from route handlers.
//
// Status, downloads and the clip go through `proxenos speech`. Speaking goes to the speech server
// that command keeps on 127.0.0.1, which holds the models in memory so a sentence takes a fraction
// of a second: this reads where it is and its token from the vault (state/speech/server.json),
// starts it when it isn't running, and passes the sentence on. Nothing here or there reaches the
// network: what's read aloud goes from this page to this Mac and back as sound.

import { promises as fs } from "node:fs";
import path from "node:path";

import { lastLine, NO_COMMAND } from "./connect";
import type { SpeechChange, SpeechEngine, SpeechStatus, SpeechStatusResponse } from "./types";
import { proxenos, vaultPath } from "./vault";

export const ENGINES: readonly SpeechEngine[] = ["natural", "own"];
/** Characters in one request, as the server takes them; Listen sends a sentence or two. */
export const MAX_SAY = 1200;
/** A clip's request: up to 4 MB of WAV, as base64, and what it says. */
export const MAX_CLIP_BODY = 6 * 1024 * 1024;

const STATUS_MS = 30_000;
const CLIP_MS = 30_000;
const START_MS = 30_000; // Python, then MLX, imported
const SAY_MS = 120_000; // a sentence, with the model loaded the first time
const PING_MS = 2_000;
const MAX_OUTPUT = 256 * 1024;
const TOKEN_HEADER = "X-Proxenos-Speech";

const folder = () => path.join(vaultPath(), "state", "speech");

/** `proxenos speech <args>`, with `stdin`, and what it printed. */
async function run(args: string[], timeout: number, stdin: string | null = null): Promise<{ out: string } | { error: string }> {
  const cli = await proxenos();
  if (!cli) return { error: NO_COMMAND };
  return new Promise((resolve) => {
    const child = cli.exec(["speech", ...args], { timeout, maxBuffer: MAX_OUTPUT }, (error, stdout, stderr) => {
      if (error) resolve({ error: error.killed ? "It took too long." : lastLine(stderr) || lastLine(stdout) || "It failed." });
      else resolve({ out: stdout });
    });
    if (stdin !== null) {
      child.stdin?.on("error", () => {});
      child.stdin?.end(stdin);
    }
  });
}

function rec(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

/** Whether this Mac can make the voices, what each needs, the clip (never its sound) and any download. */
export async function speechStatus(): Promise<SpeechStatusResponse> {
  const done = await run(["status"], STATUS_MS);
  if ("error" in done) return { status: null, error: `proxenos speech didn't answer: ${done.error}` };
  try {
    const s = rec(JSON.parse(done.out));
    if (typeof s.supported !== "boolean" || !s.engines || !Array.isArray(s.voices)) throw new Error("shape");
    return { status: s as unknown as SpeechStatus, error: null };
  } catch {
    return { status: null, error: "proxenos speech gave an answer this page can't read." };
  }
}

/** Start downloading an engine's model, on its own: the status says how far it got. */
export async function getModel(engine: SpeechEngine): Promise<SpeechChange> {
  const now = await speechStatus();
  const s = now.status;
  if (!s) return { ok: false, message: now.error ?? "Couldn't read where things stand." };
  if (!s.supported) return { ok: false, message: "A natural voice needs a Mac with Apple silicon." };
  if (!s.installed) return { ok: false, message: `Install the speech extra first: ${s.install}` };
  if (s.download?.state === "running") return { ok: true, message: "Already downloading." };
  const cli = await proxenos();
  if (!cli) return { ok: false, message: NO_COMMAND };
  const child = cli.spawn(["speech", "get", engine], { detached: true, stdio: "ignore" });
  child.on("error", () => {});
  child.unref();
  return { ok: true, message: "Downloading." };
}

/** Keep a clip of the user's voice: a 16-bit mono WAV at 24 kHz, as base64, and what it says. */
export async function saveClip(wav: string, text: string | null): Promise<SpeechChange> {
  const done = await run(["clip", "save"], CLIP_MS, JSON.stringify({ wav, text }));
  if ("error" in done) return { ok: false, message: done.error };
  try {
    const r = rec(JSON.parse(done.out));
    return r.ok === true ? { ok: true, message: "Kept." } : { ok: false, message: String(r.error ?? "It wasn't kept.") };
  } catch {
    return { ok: false, message: "proxenos speech gave an answer this page can't read." };
  }
}

/** Delete the clip, which also stops the speech server. */
export async function deleteClip(): Promise<SpeechChange> {
  const done = await run(["clip", "delete"], CLIP_MS);
  if ("error" in done) return { ok: false, message: done.error };
  return { ok: true, message: "Deleted." };
}

// ── Speaking ────────────────────────────────────────────────────────────────

interface Running {
  port: number;
  token: string;
}

async function where(): Promise<Running | null> {
  try {
    const doc = rec(JSON.parse(await fs.readFile(path.join(folder(), "server.json"), "utf8")));
    const port = Number(doc.port);
    if (!Number.isInteger(port) || port <= 0 || port > 65535 || typeof doc.token !== "string") return null;
    return { port, token: doc.token };
  } catch {
    return null;
  }
}

async function alive(server: Running): Promise<boolean> {
  try {
    const res = await fetch(`http://127.0.0.1:${server.port}/ping`, {
      headers: { [TOKEN_HEADER]: server.token },
      signal: AbortSignal.timeout(PING_MS),
      cache: "no-store",
    });
    return res.ok;
  } catch {
    return false;
  }
}

async function running(): Promise<Running | null> {
  const server = await where();
  return server && (await alive(server)) ? server : null;
}

let starting: Promise<Running | null> | null = null;

/** Start `proxenos speech serve` on its own, and wait until it answers. */
async function start(): Promise<Running | null> {
  const cli = await proxenos();
  if (!cli) return null;
  await fs.mkdir(folder(), { recursive: true, mode: 0o700 });
  // What it says starting up, for when it doesn't: never what it reads, which isn't logged.
  const log = await fs.open(path.join(folder(), "server.log"), "w", 0o600);
  let exited = false;
  try {
    const child = cli.spawn(["speech", "serve"], { detached: true, stdio: ["ignore", log.fd, log.fd] });
    child.on("exit", () => (exited = true));
    child.on("error", () => (exited = true));
    child.unref();
  } finally {
    await log.close();
  }
  const deadline = Date.now() + START_MS;
  while (Date.now() < deadline && !exited) {
    await new Promise((r) => setTimeout(r, 250));
    const server = await running();
    if (server) return server;
  }
  return null;
}

async function server(): Promise<Running | null> {
  const now = await running();
  if (now) return now;
  starting ??= start().finally(() => (starting = null));
  return starting;
}

/** Start the speech server if it isn't running, and have it load `engine`, so Listen's first sentence comes quickly. */
export async function warm(engine: SpeechEngine, voice: string | null): Promise<boolean> {
  const to = await server();
  if (!to) return false;
  try {
    const res = await fetch(`http://127.0.0.1:${to.port}/warm`, {
      method: "POST",
      headers: { "content-type": "application/json", [TOKEN_HEADER]: to.token },
      body: JSON.stringify({ engine, voice }),
      signal: AbortSignal.timeout(PING_MS),
      cache: "no-store",
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** `text` spoken by `engine` on this Mac, as a WAV, or why not (the page then reads with the device's voice). */
export async function say(
  text: string,
  engine: SpeechEngine,
  voice: string | null,
  signal: AbortSignal,
): Promise<{ audio: ArrayBuffer } | { status: number; error: string }> {
  const to = await server();
  if (!to) return { status: 503, error: "The speech server didn't start. Check Settings, Listening." };
  try {
    const res = await fetch(`http://127.0.0.1:${to.port}/speak`, {
      method: "POST",
      headers: { "content-type": "application/json", [TOKEN_HEADER]: to.token },
      body: JSON.stringify({ text, engine, voice }),
      signal: AbortSignal.any([signal, AbortSignal.timeout(SAY_MS)]),
      cache: "no-store",
    });
    if (!res.ok) {
      const answer = rec(await res.json().catch(() => ({})));
      return { status: res.status === 409 ? 409 : 502, error: String(answer.error ?? `It couldn't speak (${res.status}).`) };
    }
    return { audio: await res.arrayBuffer() };
  } catch {
    return { status: 504, error: "The speech server didn't answer." };
  }
}
