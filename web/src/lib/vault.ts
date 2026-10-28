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
  AdviceAction,
  AdviceResponse,
  BatchInfo,
  ChangelogSection,
  Confidence,
  FeedbackEntry,
  FeedItem,
  HomeResponse,
  Item,
  NetworkAction,
  NetworkResponse,
  Outreach,
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
  ToRead,
  TwinResponse,
  VaultInfo,
} from "./types";
import { ACTIONS, ADVICE_ACTIONS, NETWORK_ACTIONS, RELATIONS, TASK_ACTIONS } from "./types";

const REPO_ROOT = path.resolve(process.cwd(), "..");
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

export function vaultPath(): string {
  const configured =
    process.env.TWIN_VAULT?.trim() ||
    fromDotEnv(path.join(REPO_ROOT, ".env"), "TWIN_VAULT") ||
    "~/twin_vault";
  return path.resolve(REPO_ROOT, expandHome(configured));
}

/** First name from TWIN_NAME (environment, then the repo's .env), or null. */
export function ownerName(): string | null {
  const full = process.env.TWIN_NAME?.trim() || fromDotEnv(path.join(REPO_ROOT, ".env"), "TWIN_NAME") || "";
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

/** Parse a JSON file, or null when it is missing, too large or malformed. */
async function readJsonFile(file: string, maxBytes = MAX_CLONE_BYTES): Promise<unknown> {
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
async function appendJsonl(rel: string[], entry: object): Promise<void> {
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
async function foldLog<A extends string>(
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

/** Newest sync per source kind, from modification times only (no line counts). */
async function sourceSyncs(vault: string): Promise<SourceSync[]> {
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
  return {
    id,
    name,
    relation: RELATIONS.includes(r.relation as Relation) ? (r.relation as Relation) : "know_of",
    sources: strings(r.sources, 20).map((x) => x.toLowerCase()),
    interactions: typeof n === "number" && Number.isFinite(n) && n > 0 ? Math.round(n) : 0,
    first_seen: str(r.first_seen),
    last_seen: str(r.last_seen),
    context: str(r.context) ?? "",
    topics: strings(r.topics, 12),
    org: str(r.org)?.trim() || null,
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

export async function appendNetworkFeedback(itemId: string, action: NetworkAction) {
  const entry = { item_id: itemId, action, ts: nowIso() };
  await appendJsonl(["clones", "network", "feedback.jsonl"], entry);
  return entry;
}

// ── Home ────────────────────────────────────────────────────────────────────

/**
 * The newest dated section of a changelog. `twin master` appends "## YYYY-MM-DD"
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

  const tasks = await getTasks();
  const advice = await getAdvice();
  const network = await getNetwork();
  const unanswered = advice.suggestions.filter((s) => s.action === null);

  return {
    now: nowIso(),
    vault: await vaultInfo(vault),
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
    self: await selfSummary(vault),
    sources: await sourceSyncs(vault),
  };
}
