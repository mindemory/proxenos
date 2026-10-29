// Server-side access to the private vault. Import only from route handlers.
//
// The vault path is PROXENOS_VAULT from the environment, else from the repo's root
// .env (one level above web/), else the settings file the setup page writes, else
// ~/proxenos_vault. Every setting falls back to its older TWIN_* name when the PROXENOS_*
// one isn't set, as the Python side does. Secrets are the Python side's alone: nothing
// here reads the secure store (the Keychain, Windows Credential Manager, the Secret Service).
//
// Raw source data is never parsed here: the status view only looks at file
// names, modification times and newline counts.

import { execFile } from "node:child_process";
import { randomBytes } from "node:crypto";
import { constants as fsConstants, createReadStream, promises as fs, readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";

import type {
  Action,
  AdviceAction,
  AdviceResponse,
  BatchInfo,
  ChangelogSection,
  Cluster,
  Confidence,
  Draft,
  DraftAction,
  DraftReviews,
  DraftsResponse,
  Edge,
  FeedbackEntry,
  FeedItem,
  GraphThumb,
  Group,
  GroupKind,
  HomeResponse,
  Item,
  NetworkAction,
  NetworkResponse,
  Outreach,
  OutboxResponse,
  OutboxRuleEdit,
  OutboxRules,
  PeopleEdit,
  PeopleEditResult,
  Person,
  Project,
  Relation,
  ItemsResponse,
  Reaction,
  SelfFile,
  SourceStatus,
  SourceSync,
  StatusResponse,
  Suggestion,
  SuggestionView,
  Task,
  TaskAction,
  TaskPriority,
  TasksResponse,
  TaskStatus,
  TaskView,
  ProfileResponse,
  ToRead,
  VaultInfo,
  DraftCloseness,
} from "./types";
import { foldReviews, isAwaiting } from "./drafts";
import { GRAPH_MAX_EDGES, GRAPH_MAX_NODES } from "./graph";
import { applyOutboxEdit, cancelledIds, outboxLog, outboxRules, outboxState } from "./outbox";
import { ACTIONS, ADVICE_ACTIONS, GROUP_KINDS, NETWORK_ACTIONS, RELATIONS, TASK_ACTIONS } from "./types";

export const REPO_ROOT = path.resolve(process.cwd(), "..");
const MONTH_FILE = /^\d{4}-\d{2}\.jsonl$/;
const DAY_FILE = /^\d{4}-\d{2}-\d{2}\.json$/;
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
const MAX_SELF_BYTES = 512 * 1024;
const MAX_CLONE_BYTES = 4 * 1024 * 1024;
const MAX_PEOPLE_BYTES = 32 * 1024 * 1024;

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

/**
 * Where the setup page and Settings save settings, through `proxenos setup`: the folder each platform keeps an app's settings in,
 * found exactly as config.settings_file() finds it. On a Mac ~/Library/Application Support/Proxenos, on Windows %APPDATA%\Proxenos,
 * elsewhere $XDG_CONFIG_HOME/proxenos, else ~/.config/proxenos (a relative XDG_CONFIG_HOME doesn't count, as its spec says).
 */
export function settingsFile(): string {
  if (process.platform === "darwin") return path.join(os.homedir(), "Library", "Application Support", "Proxenos", "settings.json");
  if (process.platform === "win32") {
    return path.join(process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming"), "Proxenos", "settings.json");
  }
  const xdg = process.env.XDG_CONFIG_HOME ?? "";
  return path.join(path.isAbsolute(xdg) ? xdg : path.join(os.homedir(), ".config"), "proxenos", "settings.json");
}

/** One key of the settings file ("vault" for PROXENOS_VAULT), when it's a string. */
function fromSettings(key: string): string | undefined {
  let parsed: unknown;
  try {
    parsed = JSON.parse(readFileSync(settingsFile(), "utf8"));
  } catch {
    return undefined;
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return undefined;
  const value = (parsed as Record<string, unknown>)[key];
  return typeof value === "string" ? value.trim() || undefined : undefined;
}

/**
 * One setting: PROXENOS_<name> from the environment or the repo's .env, else the older
 * TWIN_<name> from either, else the settings file. Empty values count as unset.
 */
export function setting(name: string): string | undefined {
  const dotenv = path.join(REPO_ROOT, ".env");
  for (const key of [`PROXENOS_${name}`, `TWIN_${name}`]) {
    const value = process.env[key]?.trim() || fromDotEnv(dotenv, key);
    if (value) return value;
  }
  return fromSettings(name.toLowerCase());
}

export function vaultPath(): string {
  return path.resolve(REPO_ROOT, expandHome(setting("VAULT") ?? "~/proxenos_vault"));
}

/** First name from PROXENOS_NAME (environment, the repo's .env, then the settings file), or null. */
export function ownerName(): string | null {
  const full = setting("NAME") ?? "";
  const first = full.trim().split(/\s+/)[0] ?? "";
  return first ? first.slice(0, 40) : null;
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

export async function vaultInfo(vault: string): Promise<VaultInfo> {
  return { path: displayPath(vault), exists: await isDir(vault) };
}

export function nowIso(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

// ── JSONL ───────────────────────────────────────────────────────────────────

export async function readJsonl(file: string): Promise<unknown[]> {
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

/** Parse a JSON file, or null when it is missing, too large or malformed. */
export async function readJsonFile(file: string, maxBytes = MAX_CLONE_BYTES): Promise<unknown> {
  try {
    const st = await fs.stat(file);
    if (!st.isFile() || st.size > maxBytes) return null;
    return JSON.parse(await fs.readFile(file, "utf8"));
  } catch {
    return null;
  }
}

export class VaultMissingError extends Error {}

/** Append one JSON line to a file in the vault, creating it (and its folders) private to the user. */
export async function appendJsonl(rel: string[], entry: object): Promise<void> {
  const vault = vaultPath();
  if (!(await isDir(vault))) throw new VaultMissingError(displayPath(vault));
  const file = path.join(vault, ...rel);
  await fs.mkdir(path.dirname(file), { recursive: true, mode: 0o700 });

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

  await fs.appendFile(file, prefix + JSON.stringify(entry) + "\n", { mode: 0o600 });
}

/** Latest action per id from an append-only log (file order wins). */
export async function foldLog<A extends string>(
  file: string,
  idKey: string,
  actions: readonly A[],
): Promise<Map<string, { action: A; ts: string }>> {
  const out = new Map<string, { action: A; ts: string }>();
  for (const raw of await readJsonl(file)) {
    if (!raw || typeof raw !== "object") continue;
    const r = raw as Record<string, unknown>;
    const id = str(r[idKey]);
    const action = str(r.action) as A | null;
    if (!id || !action || !actions.includes(action)) continue;
    out.set(id, { action, ts: str(r.ts) ?? "" });
  }
  return out;
}

// ── Items and feedback ──────────────────────────────────────────────────────

function str(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

function strings(v: unknown, max = 50): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string").slice(0, max) : [];
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
    by: str(r.by) ?? "proxenos",
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

/** Append one line to tracker/feedback.jsonl, creating it with mode 0600. */
export async function appendFeedback(itemId: string, action: Action): Promise<FeedbackEntry> {
  const entry: FeedbackEntry = { item_id: itemId, action, ts: nowIso() };
  await appendJsonl(["tracker", "feedback.jsonl"], entry);
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

export async function getProfile(): Promise<ProfileResponse> {
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
  const base = { id, kind, command: `proxenos ingest ${kind}` };
  if (files.length === 0) {
    return { ...base, lastSync: null, newestMonth: null, newestMonthLines: 0, newestMonthFiles: 0 };
  }
  const newestMonth = files.reduce((m, f) => (f.month > m ? f.month : m), "");
  const newest = files.filter((f) => f.month === newestMonth);
  const lines = (await Promise.all(newest.map((f) => countLines(f.path)))).reduce((a, b) => a + b, 0);
  const lastSync = new Date(Math.max(...files.map((f) => f.mtimeMs))).toISOString();
  return { ...base, lastSync, newestMonth, newestMonthLines: lines, newestMonthFiles: newest.length };
}

/** Always listed, synced or not. */
const CORE_SOURCES = ["whatsapp", "spotify", "strava"];
/** Listed once their folder exists; until then they are named in `missing`. */
const OPTIONAL_SOURCES = ["twitter", "linkedin", "instagram", "bluesky", "website", "mentions"];
const KNOWN_SOURCES = [...CORE_SOURCES, "email", "slack", ...OPTIONAL_SOURCES];

interface SourceDir {
  id: string;
  kind: string;
  dir: string;
}

/** The folders the status view reports on, in display order. */
async function sourceDirs(raw: string): Promise<{ dirs: SourceDir[]; missing: string[] }> {
  const dirs: SourceDir[] = CORE_SOURCES.map((s) => ({ id: s, kind: s, dir: path.join(raw, s) }));

  const accounts = await subdirs(path.join(raw, "email"));
  if (accounts.length === 0) dirs.push({ id: "email", kind: "email", dir: path.join(raw, "email") });
  for (const a of accounts) dirs.push({ id: `email/${a}`, kind: "email", dir: path.join(raw, "email", a) });

  const teams = await subdirs(path.join(raw, "slack"));
  if (teams.length === 0) dirs.push({ id: "slack", kind: "slack", dir: path.join(raw, "slack") });
  for (const t of teams) {
    const messages = path.join(raw, "slack", t, "messages");
    const hasMessages = await isDir(messages);
    dirs.push({
      id: hasMessages ? `slack/${t}/messages` : `slack/${t}`,
      kind: "slack",
      dir: hasMessages ? messages : path.join(raw, "slack", t),
    });
  }

  // raw/<source>/<stream>/YYYY-MM.jsonl: one row per source, newest month summed across streams.
  const missing: string[] = [];
  for (const s of OPTIONAL_SOURCES) {
    const dir = path.join(raw, s);
    if (await isDir(dir)) dirs.push({ id: s, kind: s, dir });
    else missing.push(s);
  }

  for (const other of await subdirs(raw)) {
    if (!KNOWN_SOURCES.includes(other)) dirs.push({ id: other, kind: other, dir: path.join(raw, other) });
  }
  return { dirs, missing };
}

export async function getStatus(): Promise<StatusResponse> {
  const vault = vaultPath();
  const { dirs, missing } = await sourceDirs(path.join(vault, "raw"));
  const sources: SourceStatus[] = [];
  for (const d of dirs) sources.push(await sourceStatus(d.id, d.kind, d.dir));

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
    missing,
    tracker: {
      lastBatch: latest?.ts ?? null,
      lastBatchCount: latest?.count ?? 0,
      items,
      feedback,
    },
  };
}

// The walk below stats every month file of every stream (thousands of chats), which takes
// seconds. Sync runs every 15 minutes, so an answer up to SYNCS_FRESH_MS old is as good: it's
// served at once and refreshed behind it, and only the very first call waits.
const SYNCS_FRESH_MS = 2 * 60 * 1000;
const syncsCache = new Map<string, { at: number; value: Promise<SourceSync[]> }>();

/** Newest sync per source kind, from modification times only (no line counts). */
export async function sourceSyncs(vault: string): Promise<SourceSync[]> {
  const cached = syncsCache.get(vault);
  if (cached && Date.now() - cached.at < SYNCS_FRESH_MS) return cached.value;
  const value = walkSourceSyncs(vault);
  syncsCache.set(vault, { at: Date.now(), value });
  value.catch(() => syncsCache.delete(vault));
  if (!cached) return value;
  // Stale: answer with the last result while this one is worked out.
  return cached.value.catch(() => value);
}

async function walkSourceSyncs(vault: string): Promise<SourceSync[]> {
  const { dirs } = await sourceDirs(path.join(vault, "raw"));
  const byKind = new Map<string, number>();
  for (const d of dirs) {
    const files = await monthFiles(d.dir);
    const newest = files.length ? Math.max(...files.map((f) => f.mtimeMs)) : 0;
    byKind.set(d.kind, Math.max(byKind.get(d.kind) ?? 0, newest));
  }
  return [...byKind].map(([kind, ms]) => ({ kind, lastSync: ms ? new Date(ms).toISOString() : null }));
}

// ── Tasks clone ─────────────────────────────────────────────────────────────

const PRIORITIES: readonly TaskPriority[] = ["high", "medium", "low"];
const STATUSES: readonly TaskStatus[] = ["open", "waiting", "done"];

function toTask(raw: unknown): Task | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const id = str(r.id);
  const title = str(r.title)?.trim();
  if (!id || !title) return null;
  const due = str(r.due);
  const who = str(r.with)?.trim();
  return {
    id,
    title,
    detail: str(r.detail) ?? "",
    source: (str(r.source) ?? "unknown").toLowerCase(),
    with: who ? who : null,
    asked_at: str(r.asked_at),
    due: due && ISO_DAY.test(due) ? due : null,
    priority: PRIORITIES.includes(r.priority as TaskPriority) ? (r.priority as TaskPriority) : "medium",
    status: STATUSES.includes(r.status as TaskStatus) ? (r.status as TaskStatus) : "open",
    evidence: strings(r.evidence),
  };
}

/** tasks.json with each task's latest feedback action folded in. */
export async function getTasks(): Promise<TasksResponse> {
  const vault = vaultPath();
  const dir = path.join(vault, "clones", "tasks");
  const doc = await readJsonFile(path.join(dir, "tasks.json"));
  const d = doc && typeof doc === "object" ? (doc as Record<string, unknown>) : null;
  const acted = await foldLog<TaskAction>(path.join(dir, "feedback.jsonl"), "task_id", TASK_ACTIONS);

  const seen = new Set<string>();
  const tasks: TaskView[] = [];
  for (const raw of Array.isArray(d?.tasks) ? d.tasks : []) {
    const t = toTask(raw);
    if (!t || seen.has(t.id)) continue;
    seen.add(t.id);
    const a = acted.get(t.id);
    tasks.push({ ...t, action: a?.action ?? null, acted_at: a?.ts ?? null });
  }

  return {
    now: nowIso(),
    vault: await vaultInfo(vault),
    exists: d !== null,
    generated: d ? str(d.generated) : null,
    tasks,
  };
}

export async function appendTaskFeedback(taskId: string, action: TaskAction) {
  const entry = { task_id: taskId, action, ts: nowIso() };
  await appendJsonl(["clones", "tasks", "feedback.jsonl"], entry);
  return entry;
}

// ── Advisor clone ───────────────────────────────────────────────────────────

const CONFIDENCES: readonly Confidence[] = ["high", "medium", "low"];

function toSuggestion(raw: unknown): Suggestion | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const id = str(r.id);
  const suggestion = str(r.suggestion)?.trim();
  if (!id || !suggestion) return null;
  return {
    id,
    area: str(r.area)?.trim() || "general",
    pattern: str(r.pattern) ?? "",
    suggestion,
    why: str(r.why) ?? "",
    confidence: CONFIDENCES.includes(r.confidence as Confidence) ? (r.confidence as Confidence) : "low",
    evidence: strings(r.evidence),
  };
}

async function adviceDates(dir: string): Promise<string[]> {
  try {
    return (await fs.readdir(dir))
      .filter((n) => DAY_FILE.test(n))
      .map((n) => n.slice(0, 10))
      .sort()
      .reverse();
  } catch {
    return [];
  }
}

/** One day's advice (the newest unless `date` names another file), with feedback folded in. */
export async function getAdvice(date?: string | null): Promise<AdviceResponse> {
  const vault = vaultPath();
  const dir = path.join(vault, "clones", "advisor");
  const dates = await adviceDates(dir);
  const shown = date && dates.includes(date) ? date : (dates[0] ?? null);

  let generated: string | null = null;
  const suggestions: SuggestionView[] = [];
  if (shown) {
    const doc = await readJsonFile(path.join(dir, `${shown}.json`));
    const d = doc && typeof doc === "object" ? (doc as Record<string, unknown>) : null;
    generated = d ? str(d.generated) : null;
    const acted = await foldLog<AdviceAction>(path.join(dir, "feedback.jsonl"), "suggestion_id", ADVICE_ACTIONS);
    const seen = new Set<string>();
    for (const raw of Array.isArray(d?.suggestions) ? d.suggestions : []) {
      const s = toSuggestion(raw);
      if (!s || seen.has(s.id)) continue;
      seen.add(s.id);
      const a = acted.get(s.id);
      suggestions.push({ ...s, action: a?.action ?? null, acted_at: a?.ts ?? null });
    }
  }

  return { now: nowIso(), vault: await vaultInfo(vault), dates, date: shown, generated, suggestions };
}

export async function appendAdviceFeedback(suggestionId: string, action: AdviceAction) {
  const entry = { suggestion_id: suggestionId, action, ts: nowIso() };
  await appendJsonl(["clones", "advisor", "feedback.jsonl"], entry);
  return entry;
}

// ── Network clone ───────────────────────────────────────────────────────────

function toPerson(raw: unknown): Person | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const id = str(r.id);
  const name = str(r.name)?.trim();
  if (!id || !name) return null;
  const n = r.interactions;
  const c = r.cluster;
  return {
    id,
    name,
    relation: RELATIONS.includes(r.relation as Relation) ? (r.relation as Relation) : "know_of",
    sources: strings(r.sources, 20).map((x) => x.toLowerCase()),
    interactions: typeof n === "number" && Number.isFinite(n) && n > 0 ? Math.round(n) : 0,
    last_seen: str(r.last_seen),
    context: str(r.context) ?? "",
    topics: strings(r.topics, 12),
    org: str(r.org)?.trim() || null,
    cluster: typeof c === "number" && Number.isInteger(c) && c > 0 ? c : null,
    aka: strings(r.aka, 5).map((x) => x.slice(0, 120)),
  };
}

/** Keep the first entry per id and drop malformed ones. */
function uniqueBy<T extends { id: string }>(raws: unknown, parse: (raw: unknown) => T | null): T[] {
  const seen = new Set<string>();
  const out: T[] = [];
  for (const raw of Array.isArray(raws) ? raws : []) {
    const v = parse(raw);
    if (!v || seen.has(v.id)) continue;
    seen.add(v.id);
    out.push(v);
  }
  return out;
}

const record = (raw: unknown) => (raw && typeof raw === "object" ? (raw as Record<string, unknown>) : null);
const unacted = { action: null, acted_at: null };

function toProject(raw: unknown): Project | null {
  const r = record(raw);
  const id = str(r?.id);
  const title = str(r?.title)?.trim();
  if (!r || !id || !title) return null;
  return {
    id,
    title,
    pitch: str(r.pitch) ?? "",
    why_you: str(r.why_you) ?? "",
    people: strings(r.people, 30),
    first_step: str(r.first_step) ?? "",
    ...unacted,
  };
}

function toOutreach(raw: unknown): Outreach | null {
  const r = record(raw);
  const id = str(r?.id);
  const name = str(r?.name)?.trim();
  if (!r || !id || !name) return null;
  return {
    id,
    person_id: str(r.person_id),
    name,
    why: str(r.why) ?? "",
    ask: str(r.ask) ?? "",
    channel: (str(r.channel) ?? "").toLowerCase(),
    ...unacted,
  };
}

function toToRead(raw: unknown): ToRead | null {
  const r = record(raw);
  const id = str(r?.id);
  const name = str(r?.name)?.trim();
  if (!r || !id || !name) return null;
  return { id, name, why: str(r.why) ?? "", ...unacted };
}

function toEdge(raw: unknown): Edge | null {
  const r = record(raw);
  const source = str(r?.source);
  const target = str(r?.target);
  if (!r || !source || !target || source === target) return null;
  const w = r.weight;
  const weight = typeof w === "number" && Number.isFinite(w) && w > 0 ? w : 1;
  const n = r.shared;
  return {
    source,
    target,
    weight,
    // An index from before weights: the weight was the count.
    shared: typeof n === "number" && Number.isInteger(n) && n > 0 ? n : Math.max(1, Math.round(weight)),
    contexts: strings(r.contexts, 8),
  };
}

function toGroup(raw: unknown): Group | null {
  const r = record(raw);
  const id = str(r?.id);
  const name = str(r?.name)?.trim();
  if (!r || !id || !name || !GROUP_KINDS.includes(r.kind as GroupKind)) return null;
  const members = strings(r.members, GRAPH_MAX_NODES);
  const n = r.size;
  const size = typeof n === "number" && Number.isInteger(n) && n >= members.length ? n : members.length;
  return { id, name, kind: r.kind as GroupKind, members, size };
}

function toCluster(raw: unknown): Cluster | null {
  const r = record(raw);
  const id = r?.id;
  const label = str(r?.label)?.trim();
  const n = r?.size;
  if (!r || typeof id !== "number" || !Number.isInteger(id) || id <= 0 || !label) return null;
  return { id, label: label.slice(0, 120), size: typeof n === "number" && n > 0 ? Math.round(n) : 0 };
}

function clustersOf(raws: unknown): Cluster[] {
  const seen = new Set<number>();
  const out: Cluster[] = [];
  for (const raw of Array.isArray(raws) ? raws.slice(0, 200) : []) {
    const c = toCluster(raw);
    if (c && !seen.has(c.id)) {
      seen.add(c.id);
      out.push(c);
    }
  }
  return out;
}

/** The file's edges, strongest first, as many as the graph draws. */
function edgesOf(raws: unknown): Edge[] {
  const out: Edge[] = [];
  for (const raw of Array.isArray(raws) ? raws : []) {
    if (out.length >= GRAPH_MAX_EDGES) break;
    const e = toEdge(raw);
    if (e) out.push(e);
  }
  return out;
}

/** The people index and the ideas built on it, with feedback folded into the ideas. */
export async function getNetwork(): Promise<NetworkResponse> {
  const vault = vaultPath();
  const dir = path.join(vault, "clones", "network");
  const people = record(await readJsonFile(path.join(dir, "people.json"), MAX_PEOPLE_BYTES));
  const ideas = record(await readJsonFile(path.join(dir, "ideas.json")));
  const acted = await foldLog<NetworkAction>(path.join(dir, "feedback.jsonl"), "item_id", NETWORK_ACTIONS);
  const applyFeedback = <T extends { id: string }>(v: T): T => {
    const a = acted.get(v.id);
    return a ? { ...v, action: a.action, acted_at: a.ts } : v;
  };

  return {
    now: nowIso(),
    vault: await vaultInfo(vault),
    people: {
      exists: people !== null,
      generated: people ? str(people.generated) : null,
      list: uniqueBy(people?.people, toPerson),
      core: strings(people?.core, GRAPH_MAX_NODES),
      edges: edgesOf(people?.edges),
      groups: uniqueBy(people?.groups, toGroup),
      clusters: clustersOf(people?.clusters),
    },
    ideas: {
      exists: ideas !== null,
      generated: ideas ? str(ideas.generated) : null,
      projects: uniqueBy(ideas?.projects, toProject).map(applyFeedback),
      outreach: uniqueBy(ideas?.outreach, toOutreach).map(applyFeedback),
      to_read: uniqueBy(ideas?.to_read, toToRead).map(applyFeedback),
    },
  };
}

/** The busiest connected people and the ties among them: a small picture of the network. */
export async function getGraphThumb(limit = 140): Promise<GraphThumb> {
  const vault = vaultPath();
  const doc = record(await readJsonFile(path.join(vault, "clones", "network", "people.json"), MAX_PEOPLE_BYTES));
  const list = uniqueBy(doc?.people, toPerson);
  const edges = edgesOf(doc?.edges);
  const groups = uniqueBy(doc?.groups, toGroup);
  const byId = new Map(list.map((p) => [p.id, p]));

  // People with a tie first, the busiest of them, so the picture isn't mostly strangers.
  const degree = new Map<string, number>();
  for (const e of edges) {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
  }
  const core = strings(doc?.core, GRAPH_MAX_NODES).filter((id) => byId.has(id));
  const chosen = core
    .filter((id) => degree.has(id))
    .sort((a, b) => byId.get(b)!.interactions - byId.get(a)!.interactions)
    .slice(0, limit);
  const keep = new Set(chosen);
  return {
    now: nowIso(),
    exists: doc !== null,
    people: list.length,
    connected: core.length,
    edges: edges.length,
    groups: groups.length,
    nodes: chosen.map((id) => ({ id, relation: byId.get(id)!.relation, interactions: byId.get(id)!.interactions })),
    links: edges
      .filter((e) => keep.has(e.source) && keep.has(e.target))
      .slice(0, 600)
      .map((e) => ({ source: e.source, target: e.target, weight: e.weight })),
  };
}

export async function appendNetworkFeedback(itemId: string, action: NetworkAction) {
  const entry = { item_id: itemId, action, ts: nowIso() };
  await appendJsonl(["clones", "network", "feedback.jsonl"], entry);
  return entry;
}

// ── Who is who: clones/network/aliases.json ─────────────────────────────────
//
// {"same": [[a, b], ...], "different": [[a, b], ...], "hide": [a, ...]}. The network clone
// applies it before anything else when it builds people.json. The page writes each person as
// their "ref" from people.json (a hash of one of their ids), which still names them after a
// rebuild changes their id or name; a hand-written entry can be a name or an id too.

export class PersonNotFoundError extends Error {}

interface Aliases {
  same: string[][];
  different: string[][];
  hide: string[];
  [other: string]: unknown;
}

function aliasLists(v: unknown): string[][] {
  if (!Array.isArray(v)) return [];
  return v
    .filter((x): x is unknown[] => Array.isArray(x))
    .map((x) => x.filter((y): y is string => typeof y === "string" && y.trim() !== ""))
    .filter((x) => x.length >= 2);
}

/**
 * Apply one edit about a person to aliases.json: same and different name another person by id,
 * or (for different) one of the names this person was merged from.
 */
export async function editPeople(
  action: PeopleEdit,
  id: string,
  other?: { id: string } | { name: string },
): Promise<void> {
  const vault = vaultPath();
  if (!(await isDir(vault))) throw new VaultMissingError(displayPath(vault));
  const dir = path.join(vault, "clones", "network");
  const doc = record(await readJsonFile(path.join(dir, "people.json"), MAX_PEOPLE_BYTES));
  const list = Array.isArray(doc?.people) ? doc.people : [];
  const find = (pid: string) => {
    const found = list.map(record).find((p) => p && p.id === pid);
    if (!found) throw new PersonNotFoundError(pid);
    return found;
  };
  const refOf = (pid: string): string => {
    const ref = str(find(pid).ref);
    return ref && /^k:[0-9a-f]{16}$/.test(ref) ? ref : pid;
  };
  /** Every way an entry may name this person: ref, id, shown name, the names merged into it. */
  const namesOf = (pid: string): Set<string> => {
    const p = find(pid);
    return new Set([refOf(pid), pid, str(p.name) ?? "", ...strings(p.aka, 20)].filter(Boolean));
  };
  // Splitting off a name this person was merged from: their ref may be that very identity (a
  // first name alone with the most messages), so they're named by the name they're shown under.
  const byName = other !== undefined && "name" in other;
  const a = byName ? (str(find(id).name) ?? refOf(id)) : refOf(id);
  const b = other === undefined ? null : "id" in other ? refOf(other.id) : other.name.trim();
  const mine = namesOf(id);
  const theirs = other === undefined ? new Set<string>() : "id" in other ? namesOf(other.id) : new Set([b ?? ""]);
  const both = (xs: string[]) => xs.some((x) => mine.has(x)) && xs.some((x) => theirs.has(x));

  const file = path.join(dir, "aliases.json");
  const old = record(await readJsonFile(file)) ?? {};
  const aliases: Aliases = {
    ...old,
    same: aliasLists(old.same),
    different: aliasLists(old.different),
    hide: Array.isArray(old.hide) ? old.hide.filter((x): x is string => typeof x === "string") : [],
  };
  // The newest word on a pair wins: saying they're the same undoes saying they differ, and the
  // other way round. Splitting a name off someone undoes the merges the user made of them by hand.
  if (action === "hide") {
    if (!aliases.hide.includes(a)) aliases.hide.push(a);
  } else if (b !== null && a !== b) {
    if (action === "same") {
      aliases.different = aliases.different.filter((xs) => !both(xs));
      if (!aliases.same.some(both)) aliases.same.push([a, b]);
    } else {
      aliases.same = aliases.same.filter((xs) => (byName ? !xs.some((x) => mine.has(x)) : !both(xs)));
      if (!aliases.different.some(both)) aliases.different.push([a, b]);
    }
  }
  await fs.mkdir(dir, { recursive: true, mode: 0o700 });
  await replaceFile(file, JSON.stringify(aliases, null, 2) + "\n");
}

const REBUILD_MS = 120_000;
let rebuilding: Promise<unknown> = Promise.resolve();

/** The `proxenos` command: PROXENOS_BIN (environment, .env or settings), else the first `proxenos` on PATH. */
export async function proxenosBin(): Promise<string | null> {
  const set = setting("BIN");
  // On Windows, pip makes proxenos.exe, and a conda env keeps it in Scripts rather than bin.
  const windows = process.platform === "win32";
  const dirs = (process.env.PATH ?? "").split(path.delimiter).filter(Boolean);
  if (process.env.CONDA_PREFIX) dirs.push(path.join(process.env.CONDA_PREFIX, windows ? "Scripts" : "bin"));
  for (const candidate of set ? [expandHome(set)] : dirs.map((d) => path.join(d, windows ? "proxenos.exe" : "proxenos"))) {
    try {
      await fs.access(candidate, fsConstants.X_OK);
      return candidate;
    } catch {
      // Not here.
    }
  }
  return null;
}

/**
 * Rebuild people.json with `proxenos clone network --people-only` (no model, a few seconds), at
 * most one at a time and each after the last, with a timeout. Never throws.
 */
export function rebuildPeople(): Promise<PeopleEditResult> {
  const run = async (): Promise<PeopleEditResult> => {
    const bin = await proxenosBin();
    if (!bin) {
      return { ok: false, saved: true, rebuilt: false, message: "Couldn't find the proxenos command. Set PROXENOS_BIN in .env." };
    }
    return new Promise((resolve) => {
      execFile(
        bin,
        ["clone", "network", "--people-only"],
        { cwd: REPO_ROOT, timeout: REBUILD_MS, maxBuffer: 1024 * 1024 },
        (error, stdout) => {
          if (error) {
            const why = error.killed ? "it took too long" : "it failed";
            resolve({ ok: false, saved: true, rebuilt: false, message: `The rebuild didn't finish: ${why}.` });
          } else {
            const line = stdout.trim().split("\n").pop() ?? "";
            resolve({ ok: true, saved: true, rebuilt: true, message: line.slice(0, 300) });
          }
        },
      );
    });
  };
  const next = rebuilding.then(run, run);
  rebuilding = next;
  return next;
}

// ── Drafts ──────────────────────────────────────────────────────────────────
//
// clones/drafts/<id>.md: front matter ("key: value" lines between two "---"
// lines) and a markdown body. Nothing here sends anything; a draft is text for
// the reader to copy.

/** A draft file bigger than this isn't read, so an edit may not make one bigger either. */
export const MAX_DRAFT_BYTES = 256 * 1024;
const MAX_DRAFTS = 500;
export const DRAFT_ID = /^[A-Za-z0-9_-]{1,64}$/;

export class DraftNotFoundError extends Error {}
/** A draft with no front matter: it can be read and copied, but there's nowhere to record a status. */
export class DraftFormatError extends Error {}
export class DraftTooLargeError extends Error {}

interface DraftFile {
  name: string; // file name in the drafts folder
  text: string;
  fields: Record<string, string>;
  /** The front matter's lines, and the offset where the body starts. */
  head: { lines: string[]; end: number } | null;
}

/** A front matter value: bare text, or a quoted string as a writer might have emitted it. */
function fieldValue(raw: string): string {
  const v = raw.trim();
  if (v.length >= 2 && v[0] === '"' && v.endsWith('"')) {
    try {
      const parsed: unknown = JSON.parse(v);
      if (typeof parsed === "string") return parsed;
    } catch {
      // Not JSON after all: use it as written, without the quotes.
    }
    return v.slice(1, -1);
  }
  if (v.length >= 2 && v[0] === "'" && v.endsWith("'")) return v.slice(1, -1);
  return v;
}

function readDraftFile(name: string, text: string): DraftFile {
  const bare = text.replace(/^\uFEFF/, "");
  const m = bare.match(/^---[ \t]*\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/);
  if (!m) return { name, text: bare, fields: {}, head: null };
  const fields: Record<string, string> = {};
  const lines = m[1].split(/\r?\n/);
  for (const line of lines) {
    const kv = line.match(/^([A-Za-z_][\w-]*)\s*:\s*(.*)$/);
    if (kv && !(kv[1].toLowerCase() in fields)) fields[kv[1].toLowerCase()] = fieldValue(kv[2]);
  }
  return { name, text: bare, fields, head: { lines, end: m[0].length } };
}

function toDraft(file: DraftFile): Draft {
  const f = file.fields;
  const stem = file.name.replace(/\.md$/i, "");
  const body = file.head ? file.text.slice(file.head.end) : file.text;
  const created = f.created && !Number.isNaN(Date.parse(f.created)) ? f.created : null;
  return {
    id: f.id && DRAFT_ID.test(f.id) ? f.id : stem,
    title: f.title?.trim() || "Untitled draft",
    kind: (f.kind ?? "").trim().toLowerCase(),
    for: (f.for ?? "").trim().toLowerCase(),
    channel: (f.channel ?? "").trim().toLowerCase(),
    to: (f.to ?? "").trim(),
    created,
    status: (f.status ?? "draft").trim().toLowerCase() || "draft",
    body: body.replace(/\r\n?/g, "\n").replace(/^(?:[ \t]*\n)+/, "").replace(/\s+$/, ""),
    found: (f.found ?? "").trim(),
    asks: stringList(f.asks),
  };
}

/** A front matter value written as a JSON list of strings; [] for anything else. */
function stringList(raw: string | undefined): string[] {
  try {
    const parsed: unknown = JSON.parse(raw ?? "");
    return Array.isArray(parsed) ? parsed.filter((a): a is string => typeof a === "string" && a.trim() !== "") : [];
  } catch {
    return [];
  }
}

function draftsDir(vault: string): string {
  return path.join(vault, "clones", "drafts");
}

/**
 * The draft files, most recently written first, at most MAX_DRAFTS of them. Only
 * plain files count: a symlink in the folder could point anywhere, so it's never
 * read, and never written through.
 */
async function readDraftFiles(vault: string): Promise<DraftFile[]> {
  const dir = draftsDir(vault);
  let names: string[];
  try {
    names = (await fs.readdir(dir)).filter((n) => n.toLowerCase().endsWith(".md") && !n.startsWith("."));
  } catch {
    return [];
  }
  const found: { name: string; mtime: number }[] = [];
  for (const name of names) {
    try {
      const st = await fs.lstat(path.join(dir, name));
      if (st.isFile() && st.size <= MAX_DRAFT_BYTES) found.push({ name, mtime: st.mtimeMs });
    } catch {
      // Vanished: skip it.
    }
  }
  found.sort((a, b) => b.mtime - a.mtime || a.name.localeCompare(b.name));
  const out: DraftFile[] = [];
  for (const { name } of found.slice(0, MAX_DRAFTS)) {
    try {
      // O_NOFOLLOW: a file swapped for a symlink since the lstat above isn't followed either.
      const fh = await fs.open(path.join(dir, name), fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW);
      try {
        out.push(readDraftFile(name, await fh.readFile("utf8")));
      } finally {
        await fh.close();
      }
    } catch {
      // Vanished or unreadable: skip it.
    }
  }
  return out;
}

/** Every draft, newest first. Each is exactly what its file says; nothing is made up for a bad file. */
export async function getDrafts(): Promise<DraftsResponse> {
  const vault = vaultPath();
  const seen = new Set<string>();
  const drafts: Draft[] = [];
  for (const file of await readDraftFiles(vault)) {
    const d = toDraft(file);
    if (seen.has(d.id)) continue;
    seen.add(d.id);
    drafts.push(d);
  }
  drafts.sort((a, b) => time(b.created ?? "") - time(a.created ?? "") || a.title.localeCompare(b.title));
  return { now: nowIso(), vault: await vaultInfo(vault), exists: await isDir(draftsDir(vault)), drafts };
}

/**
 * Write a file next to its old self and swap it in, so a reader never sees half of it.
 * The new file is private to the user, like everything else the page writes to the vault,
 * and the temporary one is created fresh ("wx"), never opened through something already there.
 */
async function replaceFile(file: string, text: string): Promise<void> {
  const tmp = path.join(path.dirname(file), `.${path.basename(file)}.${randomBytes(6).toString("hex")}.tmp`);
  try {
    await fs.writeFile(tmp, text, { mode: 0o600, flag: "wx" });
    await fs.rename(tmp, file);
  } catch (e) {
    await fs.rm(tmp, { force: true });
    throw e;
  }
}

/** The file's text with one front matter field set, added at the end of the front matter if it's missing. */
function withField(file: DraftFile, key: string, value: string): string {
  const head = file.head;
  if (!head) throw new Error("no front matter");
  const eol = file.text.includes("\r\n") ? "\r\n" : "\n";
  const lines = [...head.lines];
  const at = lines.findIndex((l) => new RegExp(`^${key}\\s*:`, "i").test(l));
  if (at === -1) lines.push(`${key}: ${value}`);
  else lines[at] = `${key}: ${value}`;
  return `---${eol}${lines.join(eol)}${eol}---${eol}${file.text.slice(head.end)}`;
}

/** The file's text with a new body under the same front matter. */
function withBody(file: DraftFile, body: string): string {
  const head = file.head;
  if (!head) throw new Error("no front matter");
  const eol = file.text.includes("\r\n") ? "\r\n" : "\n";
  const lines = head.lines.join(eol);
  return `---${eol}${lines}${eol}---${eol}${eol}${body.replace(/\r\n?/g, "\n").replace(/\s+$/, "").replace(/\n/g, eol)}${eol}`;
}

/** What each action that changes a draft's file sets its status to. The others only log. */
const STATUS_OF: Partial<Record<DraftAction, string>> = { approve: "approved", discard: "discarded", sent: "sent" };

/** How the reader has reviewed drafts so far, from clones/drafts/feedback.jsonl. */
export async function getDraftReviews(vault: string = vaultPath()): Promise<DraftReviews> {
  return foldReviews(await readJsonl(path.join(draftsDir(vault), "feedback.jsonl")));
}

/** How close reply drafts came to what was sent, from the sync's measure; null before any. */
export async function getDraftCloseness(vault: string = vaultPath()): Promise<DraftCloseness | null> {
  const raw = (await readJsonFile(path.join(draftsDir(vault), "fidelity.json")).catch(() => null)) as {
    drafts?: { closeness?: unknown }[];
    by_source?: Record<string, { n?: unknown; mean?: unknown }>;
  } | null;
  const drafts = Array.isArray(raw?.drafts) ? raw.drafts : [];
  if (drafts.length === 0) return null;
  const bySource: DraftCloseness["bySource"] = {};
  for (const [source, s] of Object.entries(raw?.by_source ?? {})) {
    if (typeof s?.n === "number" && typeof s?.mean === "number") bySource[source] = { n: s.n, mean: s.mean };
  }
  const sentAsIs = drafts.filter((d) => typeof d.closeness === "number" && d.closeness >= 0.95).length;
  return { measured: drafts.length, sentAsIs, bySource };
}

/**
 * Apply one action to a draft: approve, discard and sent set its status, edit
 * replaces its body, copy and opened only log. Each is then appended to
 * clones/drafts/feedback.jsonl as {draft_id, action, ts}. The draft is found by
 * matching the id against the files that exist, never by building a path from it.
 */
export async function applyDraftAction(draftId: string, action: DraftAction, body?: string) {
  const vault = vaultPath();
  if (!(await isDir(vault))) throw new VaultMissingError(displayPath(vault));
  const file = (await readDraftFiles(vault)).find((f) => toDraft(f).id === draftId);
  if (!file) throw new DraftNotFoundError(draftId);

  const status = STATUS_OF[action];
  if (action === "edit" || status) {
    if (!file.head) throw new DraftFormatError(draftId);
    const text = status ? withField(file, "status", status) : withBody(file, body ?? "");
    if (Buffer.byteLength(text, "utf8") > MAX_DRAFT_BYTES) throw new DraftTooLargeError(draftId);
    await replaceFile(path.join(draftsDir(vault), file.name), text);
  }

  const entry = { draft_id: draftId, action, ts: nowIso() };
  await appendJsonl(["clones", "drafts", "feedback.jsonl"], entry);
  return entry;
}

// ── Outbox ──────────────────────────────────────────────────────────────────
//
// clones/outbox/: rules.json (the page writes it, the sync reads it), state.json and log.jsonl
// (the sync writes them, the page reads them) and cancelled.jsonl (the page appends to it). The
// page never sends anything: it only says what may be sent, and what may not after all.

function outboxDir(vault: string): string {
  return path.join(vault, "clones", "outbox");
}

/** The rules, what the last sync worked out, which replies were cancelled, and the newest attempts. */
export async function getOutbox(vault: string = vaultPath()): Promise<OutboxResponse> {
  const dir = outboxDir(vault);
  const [rules, state, cancelled, log] = await Promise.all([
    readJsonFile(path.join(dir, "rules.json")),
    readJsonFile(path.join(dir, "state.json")),
    readJsonl(path.join(dir, "cancelled.jsonl")),
    readJsonl(path.join(dir, "log.jsonl")),
  ]);
  return {
    now: nowIso(),
    rules: outboxRules(rules),
    state: outboxState(state),
    cancelled: cancelledIds(cancelled),
    log: outboxLog(log),
  };
}

let savingRules: Promise<unknown> = Promise.resolve();

/**
 * Apply one checked edit to rules.json, filling in what the file lacks, and give back the rules as
 * saved. Edits are made one after another, so two at once can't undo each other.
 */
export function saveOutboxRules(edit: OutboxRuleEdit): Promise<OutboxRules> {
  const run = async (): Promise<OutboxRules> => {
    const vault = vaultPath();
    if (!(await isDir(vault))) throw new VaultMissingError(displayPath(vault));
    const dir = outboxDir(vault);
    const file = path.join(dir, "rules.json");
    const rules = applyOutboxEdit(outboxRules(await readJsonFile(file)), edit);
    await fs.mkdir(dir, { recursive: true, mode: 0o700 });
    await replaceFile(file, JSON.stringify(rules, null, 2) + "\n");
    return rules;
  };
  const next = savingRules.then(run, run);
  savingRules = next;
  return next;
}

/** Say a queued reply is not to go: one line in clones/outbox/cancelled.jsonl, which the sync honours. */
export async function appendOutboxCancel(draftId: string): Promise<void> {
  await appendJsonl(["clones", "outbox", "cancelled.jsonl"], { draft_id: draftId, at: nowIso() });
}

// ── Home ────────────────────────────────────────────────────────────────────

/**
 * The newest dated section of a changelog. `proxenos master` appends "## YYYY-MM-DD"
 * and then free-form markdown that may carry its own headings, so a section runs
 * to the next dated heading, and on a repeated date the later entry wins.
 */
function newestChangelogSection(md: string): ChangelogSection | null {
  const lines = md.replace(/\r\n?/g, "\n").split("\n");
  const heads: { i: number; level: number; text: string; date: string | null }[] = [];
  let fenced = false;
  lines.forEach((line, i) => {
    if (line.trim().startsWith("```")) fenced = !fenced;
    const m = fenced ? null : line.match(/^(#{1,6})\s+(.*)$/);
    if (m) heads.push({ i, level: m[1].length, text: m[2].trim(), date: m[2].match(/\d{4}-\d{2}-\d{2}/)?.[0] ?? null });
  });
  let best: (typeof heads)[number] | null = null;
  for (const h of heads) if (h.date && (!best || h.date >= best.date!)) best = h;
  if (!best) return null;
  const next = heads.find((h) => h.i > best.i && h.date && h.level <= best.level);
  const body = lines.slice(best.i + 1, next ? next.i : lines.length).join("\n").trim();
  return { heading: best.text, date: best.date!, body: body.slice(0, 4000) };
}

async function selfSummary(vault: string): Promise<HomeResponse["self"]> {
  const dir = path.join(vault, "self");
  let names: string[] = [];
  try {
    names = (await fs.readdir(dir)).filter((n) => n.endsWith(".md") && !n.startsWith("."));
  } catch {
    // No self/ yet.
  }
  let updated = 0;
  for (const n of names) {
    try {
      updated = Math.max(updated, (await fs.stat(path.join(dir, n))).mtimeMs);
    } catch {
      // Vanished mid-scan.
    }
  }
  let latest: ChangelogSection | null = null;
  if (names.includes("CHANGELOG.md")) {
    try {
      const fh = await fs.open(path.join(dir, "CHANGELOG.md"), "r");
      try {
        const buf = Buffer.alloc(Math.min((await fh.stat()).size, MAX_SELF_BYTES));
        await fh.read(buf, 0, buf.length, 0);
        latest = newestChangelogSection(buf.toString("utf8"));
      } finally {
        await fh.close();
      }
    } catch {
      // Unreadable changelog: show only the modification time.
    }
  }
  return { exists: names.length > 0, updated: updated ? new Date(updated).toISOString() : null, latest };
}

/** Everything the opening brief shows, relative to the reader's last visit. */
export async function getHome(since: string | null): Promise<HomeResponse> {
  const vault = vaultPath();
  const sinceMs = since ? time(since) : 0;

  // Feed: items newer than the last visit, or the latest batch on a first visit.
  const latestFeed = await getFeed(1);
  let pool: FeedItem[] = latestFeed.items;
  if (sinceMs) {
    const sinceMonth = new Date(sinceMs).toISOString().slice(0, 7);
    const byId = new Map<string, Item>();
    for (const file of await itemFiles(vault)) {
      if (path.basename(file).slice(0, 7) < sinceMonth) break;
      for (const it of await readItems(file)) {
        if (time(it.ts) <= sinceMs) continue;
        const prev = byId.get(it.id);
        if (!prev || time(it.ts) > time(prev.ts)) byId.set(it.id, it);
      }
    }
    const state = foldFeedback(await readFeedback(vault));
    pool = [...byId.values()].map((it) => withState(it, state));
  }
  const top = pool
    .filter((it) => it.reaction !== "not_me")
    .sort((a, b) => Number(a.explore) - Number(b.explore) || b.score - a.score)
    .slice(0, 3);

  // Independent reads, side by side: the page waits for the slowest, not for all of them in turn.
  const [tasks, advice, network, drafts, info, self, sources] = await Promise.all([
    getTasks(),
    getAdvice(),
    getNetwork(),
    getDrafts(),
    vaultInfo(vault),
    selfSummary(vault),
    sourceSyncs(vault),
  ]);
  const unanswered = advice.suggestions.filter((s) => s.action === null);
  const awaiting = drafts.drafts.filter((d) => isAwaiting(d.status));

  return {
    now: nowIso(),
    vault: info,
    name: ownerName(),
    since: sinceMs ? new Date(sinceMs).toISOString() : null,
    feed: { newCount: pool.length, top, latest: latestFeed.latest },
    tasks: {
      exists: tasks.exists,
      generated: tasks.generated,
      actionable: tasks.tasks.filter((t) => t.status === "open" && t.action === null),
      waiting: tasks.tasks.filter((t) => t.status === "waiting" && t.action === null).length,
    },
    advice: {
      exists: advice.date !== null,
      date: advice.date,
      generated: advice.generated,
      total: advice.suggestions.length,
      unanswered: unanswered.length,
      pick: unanswered[0] ?? advice.suggestions[0] ?? null,
    },
    network: {
      exists: network.people.exists,
      people: network.people.list.length,
      met: network.people.list.filter((p) => p.relation === "met").length,
      outreach: network.ideas.outreach.find((o) => o.action === null) ?? null,
    },
    drafts: { exists: drafts.exists, awaiting: awaiting.length, top: awaiting.slice(0, 3) },
    self,
    sources,
  };
}
