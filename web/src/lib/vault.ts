// Server-side access to the private vault. Import only from route handlers.
//
// The vault path is TWIN_VAULT from the environment, else TWIN_VAULT from the
// repo's root .env (one level above web/), else ~/twin_vault.
//
// Raw source data is never parsed here: the status view only looks at file
// names, modification times and newline counts.

import { createReadStream, promises as fs, readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";

import type {
  Action,
  BatchInfo,
  FeedbackEntry,
  FeedItem,
  Item,
  ItemsResponse,
  Reaction,
  SelfFile,
  SourceStatus,
  StatusResponse,
  TwinResponse,
  VaultInfo,
} from "./types";
import { ACTIONS } from "./types";

const REPO_ROOT = path.resolve(process.cwd(), "..");
const MONTH_FILE = /^\d{4}-\d{2}\.jsonl$/;
const MAX_SELF_BYTES = 512 * 1024;

// ── Vault location ──────────────────────────────────────────────────────────

function expandHome(p: string): string {
  if (p === "~") return os.homedir();
  if (p.startsWith("~/")) return path.join(os.homedir(), p.slice(2));
  return p;
}

/** Read one key from a dotenv file. Only that key's value is kept. */
function fromDotEnv(file: string, key: string): string | undefined {
  let text: string;
  try {
    text = readFileSync(file, "utf8");
  } catch {
    return undefined;
  }
  let value: string | undefined;
  for (const line of text.split(/\r?\n/)) {
    const m = line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (!m || m[1] !== key) continue;
    let v = m[2];
    const q = v[0];
    if ((q === '"' || q === "'") && v.length >= 2 && v.endsWith(q)) v = v.slice(1, -1);
    else v = v.replace(/\s+#.*$/, "");
    value = v;
  }
  return value || undefined;
}

export function vaultPath(): string {
  const configured =
    process.env.TWIN_VAULT?.trim() ||
    fromDotEnv(path.join(REPO_ROOT, ".env"), "TWIN_VAULT") ||
    "~/twin_vault";
  return path.resolve(REPO_ROOT, expandHome(configured));
}

function displayPath(p: string): string {
  const home = os.homedir();
  return p === home || p.startsWith(home + path.sep) ? "~" + p.slice(home.length) : p;
}

async function isDir(p: string): Promise<boolean> {
  try {
    return (await fs.stat(p)).isDirectory();
  } catch {
    return false;
  }
}

async function vaultInfo(vault: string): Promise<VaultInfo> {
  return { path: displayPath(vault), exists: await isDir(vault) };
}

function nowIso(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

// ── JSONL ───────────────────────────────────────────────────────────────────

async function readJsonl(file: string): Promise<unknown[]> {
  let text: string;
  try {
    text = await fs.readFile(file, "utf8");
  } catch {
    return [];
  }
  const out: unknown[] = [];
  for (const line of text.split("\n")) {
    const s = line.trim();
    if (!s) continue;
    try {
      out.push(JSON.parse(s));
    } catch {
      // A torn or hand-edited line should not take the page down.
    }
  }
  return out;
}

/** Count newline-terminated lines without decoding the contents. */
function countLines(file: string): Promise<number> {
  return new Promise((resolve) => {
    let lines = 0;
    let size = 0;
    let last = 10;
    const stream = createReadStream(file);
    stream.on("data", (chunk) => {
      const buf = chunk as Buffer;
      size += buf.length;
      for (let i = buf.indexOf(10); i !== -1; i = buf.indexOf(10, i + 1)) lines++;
      if (buf.length) last = buf[buf.length - 1];
    });
    stream.on("end", () => resolve(size > 0 && last !== 10 ? lines + 1 : lines));
    stream.on("error", () => resolve(0));
  });
}

// ── Items and feedback ──────────────────────────────────────────────────────

function str(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

function safeUrl(v: unknown): string {
  const s = str(v);
  if (!s) return "";
  try {
    const u = new URL(s);
    return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : "";
  } catch {
    return "";
  }
}

function toItem(raw: unknown): Item | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const id = str(r.id);
  const title = str(r.title);
  if (!id || !title) return null;
  const kind = r.kind === "paper" || r.kind === "news" || r.kind === "post" ? r.kind : "post";
  const score =
    typeof r.score === "number" && Number.isFinite(r.score) ? Math.min(1, Math.max(0, r.score)) : 0;
  const ts = str(r.ts) ?? "";
  return {
    id,
    ts,
    batch: str(r.batch) ?? ts,
    url: safeUrl(r.url),
    title,
    source: str(r.source) ?? "unknown",
    kind,
    published: str(r.published),
    authors: Array.isArray(r.authors)
      ? r.authors.filter((a): a is string => typeof a === "string")
      : null,
    summary: str(r.summary) ?? "",
    score,
    why: str(r.why) ?? "",
    interest: str(r.interest) ?? "",
    explore: r.explore === true,
    by: str(r.by) ?? "twin",
  };
}

/** Month files in tracker/items, newest first. */
async function itemFiles(vault: string): Promise<string[]> {
  const dir = path.join(vault, "tracker", "items");
  try {
    const names = await fs.readdir(dir);
    return names
      .filter((n) => MONTH_FILE.test(n))
      .sort()
      .reverse()
      .map((n) => path.join(dir, n));
  } catch {
    return [];
  }
}

async function readItems(file: string): Promise<Item[]> {
  return (await readJsonl(file)).map(toItem).filter((i): i is Item => i !== null);
}

function feedbackFile(vault: string): string {
  return path.join(vault, "tracker", "feedback.jsonl");
}

async function readFeedback(vault: string): Promise<FeedbackEntry[]> {
  const rows = await readJsonl(feedbackFile(vault));
  const out: FeedbackEntry[] = [];
  for (const raw of rows) {
    if (!raw || typeof raw !== "object") continue;
    const r = raw as Record<string, unknown>;
    const itemId = str(r.item_id);
    const action = str(r.action) as Action | null;
    if (!itemId || !action || !ACTIONS.includes(action)) continue;
    out.push({ item_id: itemId, action, ts: str(r.ts) ?? "" });
  }
  return out;
}

interface ItemState {
  reaction: Reaction | null;
  reacted_at: string | null;
  opened: boolean;
}

/** Fold the append-only log into each item's latest reaction (file order wins). */
function foldFeedback(entries: FeedbackEntry[]): Map<string, ItemState> {
  const state = new Map<string, ItemState>();
  for (const e of entries) {
    const s = state.get(e.item_id) ?? { reaction: null, reacted_at: null, opened: false };
    if (e.action === "open") s.opened = true;
    else {
      s.reaction = e.action;
      s.reacted_at = e.ts;
    }
    state.set(e.item_id, s);
  }
  return state;
}

function withState(item: Item, state: Map<string, ItemState>): FeedItem {
  return { ...item, ...(state.get(item.id) ?? { reaction: null, reacted_at: null, opened: false }) };
}

function time(iso: string): number {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? 0 : t;
}

function batchesOf(items: Item[]): BatchInfo[] {
  const map = new Map<string, BatchInfo>();
  for (const it of items) {
    const b = map.get(it.batch) ?? { batch: it.batch, ts: it.ts, count: 0 };
    b.count++;
    if (time(it.ts) > time(b.ts)) b.ts = it.ts;
    map.set(it.batch, b);
  }
  return [...map.values()].sort((a, b) => time(b.ts) - time(a.ts));
}

/** Items from the newest `limit` batches: newest batch first, then by score. */
export async function getFeed(limit: number): Promise<ItemsResponse> {
  const vault = vaultPath();
  const byId = new Map<string, Item>();
  for (const file of await itemFiles(vault)) {
    for (const it of await readItems(file)) {
      const prev = byId.get(it.id);
      if (!prev || time(it.ts) > time(prev.ts)) byId.set(it.id, it);
    }
    // Month files hold batches in time order, so older files only matter
    // until we have enough batches.
    if (batchesOf([...byId.values()]).length >= limit) break;
  }

  const batches = batchesOf([...byId.values()]).slice(0, limit);
  const rank = new Map(batches.map((b, i) => [b.batch, i]));
  const state = foldFeedback(await readFeedback(vault));
  const items = [...byId.values()]
    .filter((it) => rank.has(it.batch))
    .sort((a, b) => rank.get(a.batch)! - rank.get(b.batch)! || b.score - a.score)
    .map((it) => withState(it, state));

  return {
    now: nowIso(),
    vault: await vaultInfo(vault),
    view: "feed",
    items,
    batches,
    latest: batches[0] ?? null,
  };
}

/** Items whose latest reaction is "save", most recently saved first. */
export async function getSaved(): Promise<ItemsResponse> {
  const vault = vaultPath();
  const state = foldFeedback(await readFeedback(vault));
  const wanted = new Set([...state].filter(([, s]) => s.reaction === "save").map(([id]) => id));
  const found = new Map<string, Item>();
  for (const file of await itemFiles(vault)) {
    if (found.size === wanted.size) break;
    for (const it of await readItems(file)) {
      if (wanted.has(it.id) && !found.has(it.id)) found.set(it.id, it);
    }
  }
  const items = [...found.values()]
    .map((it) => withState(it, state))
    .sort((a, b) => time(b.reacted_at ?? "") - time(a.reacted_at ?? ""));

  return {
    now: nowIso(),
    vault: await vaultInfo(vault),
    view: "saved",
    items,
    batches: [],
    latest: null,
  };
}

export class VaultMissingError extends Error {}

/** Append one line to tracker/feedback.jsonl, creating it with mode 0600. */
export async function appendFeedback(itemId: string, action: Action): Promise<FeedbackEntry> {
  const vault = vaultPath();
  if (!(await isDir(vault))) throw new VaultMissingError(displayPath(vault));
  await fs.mkdir(path.join(vault, "tracker"), { recursive: true, mode: 0o700 });
  const file = feedbackFile(vault);

  // If something else left the file without a trailing newline, don't glue lines together.
  let prefix = "";
  try {
    const fh = await fs.open(file, "r");
    try {
      const { size } = await fh.stat();
      if (size > 0) {
        const last = Buffer.alloc(1);
        await fh.read(last, 0, 1, size - 1);
        if (last[0] !== 10) prefix = "\n";
      }
    } finally {
      await fh.close();
    }
  } catch {
    // Missing file: appendFile creates it below.
  }

  const entry: FeedbackEntry = { item_id: itemId, action, ts: nowIso() };
  await fs.appendFile(file, prefix + JSON.stringify(entry) + "\n", { mode: 0o600 });
  return entry;
}

// ── Self-model ──────────────────────────────────────────────────────────────

const SELF_ORDER = [
  "identity.md",
  "interests.md",
  "taste.md",
  "voice.md",
  "routines.md",
  "open_questions.md",
  "CHANGELOG.md",
];

export async function getTwin(): Promise<TwinResponse> {
  const vault = vaultPath();
  const dir = path.join(vault, "self");
  let names: string[] = [];
  try {
    names = (await fs.readdir(dir)).filter((n) => n.endsWith(".md") && !n.startsWith("."));
  } catch {
    // No self/ yet.
  }
  const order = (n: string) => {
    const i = SELF_ORDER.indexOf(n);
    return i === -1 ? SELF_ORDER.length : i;
  };
  names.sort((a, b) => order(a) - order(b) || a.localeCompare(b));

  const files: SelfFile[] = [];
  for (const name of names) {
    const p = path.join(dir, name);
    try {
      const st = await fs.stat(p);
      if (!st.isFile()) continue;
      const fh = await fs.open(p, "r");
      try {
        const buf = Buffer.alloc(Math.min(st.size, MAX_SELF_BYTES));
        await fh.read(buf, 0, buf.length, 0);
        files.push({ name, mtime: st.mtime.toISOString(), content: buf.toString("utf8") });
      } finally {
        await fh.close();
      }
    } catch {
      // Skip unreadable files.
    }
  }
  return { now: nowIso(), vault: await vaultInfo(vault), files };
}

// ── Status ──────────────────────────────────────────────────────────────────

interface MonthFile {
  path: string;
  month: string;
  mtimeMs: number;
}

/** All YYYY-MM.jsonl files under dir. Hidden entries and symlinks are skipped. */
async function monthFiles(dir: string): Promise<MonthFile[]> {
  let entries;
  try {
    entries = await fs.readdir(dir, { withFileTypes: true });
  } catch {
    return [];
  }
  const out: MonthFile[] = [];
  for (const e of entries) {
    if (e.name.startsWith(".")) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...(await monthFiles(p)));
    else if (e.isFile() && MONTH_FILE.test(e.name)) {
      try {
        out.push({ path: p, month: e.name.slice(0, 7), mtimeMs: (await fs.stat(p)).mtimeMs });
      } catch {
        // Vanished mid-scan.
      }
    }
  }
  return out;
}

async function subdirs(dir: string): Promise<string[]> {
  try {
    const entries = await fs.readdir(dir, { withFileTypes: true });
    return entries
      .filter((e) => e.isDirectory() && !e.name.startsWith("."))
      .map((e) => e.name)
      .sort();
  } catch {
    return [];
  }
}

async function sourceStatus(id: string, kind: string, dir: string): Promise<SourceStatus> {
  const files = await monthFiles(dir);
  const base = { id, kind, command: `twin ingest ${kind}` };
  if (files.length === 0) {
    return { ...base, lastSync: null, newestMonth: null, newestMonthLines: 0, newestMonthFiles: 0 };
  }
  const newestMonth = files.reduce((m, f) => (f.month > m ? f.month : m), "");
  const newest = files.filter((f) => f.month === newestMonth);
  const lines = (await Promise.all(newest.map((f) => countLines(f.path)))).reduce((a, b) => a + b, 0);
  const lastSync = new Date(Math.max(...files.map((f) => f.mtimeMs))).toISOString();
  return { ...base, lastSync, newestMonth, newestMonthLines: lines, newestMonthFiles: newest.length };
}

const KNOWN_SOURCES = ["whatsapp", "spotify", "strava", "email", "slack"];

export async function getStatus(): Promise<StatusResponse> {
  const vault = vaultPath();
  const raw = path.join(vault, "raw");
  const sources: SourceStatus[] = [];

  for (const s of ["whatsapp", "spotify", "strava"]) {
    sources.push(await sourceStatus(s, s, path.join(raw, s)));
  }

  const accounts = await subdirs(path.join(raw, "email"));
  if (accounts.length === 0) sources.push(await sourceStatus("email", "email", path.join(raw, "email")));
  for (const a of accounts) {
    sources.push(await sourceStatus(`email/${a}`, "email", path.join(raw, "email", a)));
  }

  const teams = await subdirs(path.join(raw, "slack"));
  if (teams.length === 0) sources.push(await sourceStatus("slack", "slack", path.join(raw, "slack")));
  for (const t of teams) {
    const messages = path.join(raw, "slack", t, "messages");
    const hasMessages = await isDir(messages);
    sources.push(
      await sourceStatus(
        hasMessages ? `slack/${t}/messages` : `slack/${t}`,
        "slack",
        hasMessages ? messages : path.join(raw, "slack", t),
      ),
    );
  }

  for (const other of await subdirs(raw)) {
    if (!KNOWN_SOURCES.includes(other)) sources.push(await sourceStatus(other, other, path.join(raw, other)));
  }

  // Tracker: newest batch, plus totals across every month file.
  const files = await itemFiles(vault);
  let items = 0;
  let latest: BatchInfo | null = null;
  for (const file of files) {
    const its = await readItems(file);
    items += its.length;
    if (!latest) latest = batchesOf(its)[0] ?? null;
  }
  const feedback = (await readFeedback(vault)).length;

  return {
    now: nowIso(),
    vault: await vaultInfo(vault),
    sources,
    tracker: {
      lastBatch: latest?.ts ?? null,
      lastBatchCount: latest?.count ?? 0,
      items,
      feedback,
    },
  };
}
