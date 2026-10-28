// Server-side access to the memory index (vault/memory/index.sqlite) and to today's recall
// (vault/clones/recall/today.json). Import only from route handlers.
//
// The index is written by `twin index` and only ever read here: each request opens it read-only,
// runs parameterised queries and closes it, so a rebuild that swaps the file in is picked up at
// once. SQLite comes from Node itself (node:sqlite, Node 22.13 or newer), so there is no native
// package to install. Text typed by the reader is never put into SQL, and is quoted word by word
// before it reaches FTS5, so it can't mean anything but words; ftsQuery mirrors fts_query in
// src/twin/memory.py.

import { existsSync, promises as fs } from "node:fs";
import path from "node:path";

import type {
  MemoryContextResponse,
  MemoryFacet,
  MemoryHit,
  MemoryRecord,
  MemorySearchResponse,
  RecallKind,
  RecallResponse,
  RecallTrigger,
} from "./types";
import { MARK_END, MARK_START } from "./memoryMarks";
import { vaultPath } from "./vault";

const SNIPPET_TOKENS = 32;
const MAX_TERMS = 16;
const MAX_TERM_CHARS = 64;
// bm25 weights in the table's column order: id, source, stream, ts, who, where_, title, text, from_me.
const WEIGHTS = "0.0, 0.0, 0.0, 0.0, 2.0, 1.0, 3.0, 1.0, 0.0";
const MAX_RECALL_BYTES = 8 * 1024 * 1024;

export class MemoryUnavailableError extends Error {}

// ── node:sqlite, typed by hand (the installed @types/node predates it) ─────

type SqlValue = string | number | null;
interface Statement {
  all(...params: SqlValue[]): Record<string, unknown>[];
  get(...params: SqlValue[]): Record<string, unknown> | undefined;
}
interface Database {
  prepare(sql: string): Statement;
  exec(sql: string): void;
  close(): void;
}
interface SqliteModule {
  DatabaseSync: new (file: string, options?: { readOnly?: boolean; timeout?: number }) => Database;
}

function sqlite(): SqliteModule {
  // getBuiltinModule keeps the bundler out of it: node:sqlite is resolved by Node at run time.
  const mod = process.getBuiltinModule?.("node:sqlite") as unknown as SqliteModule | undefined;
  if (!mod) throw new MemoryUnavailableError("Memory search needs Node 22.13 or newer.");
  return mod;
}

function indexFile(): string {
  return path.join(vaultPath(), "memory", "index.sqlite");
}

/** Run `work` against the index, or return `none` when there is no index yet. */
function withIndex<T>(none: T, work: (db: Database) => T): T {
  const file = indexFile();
  if (!existsSync(file)) return none;
  const db = new (sqlite().DatabaseSync)(file, { readOnly: true, timeout: 3000 });
  try {
    db.exec("PRAGMA busy_timeout = 3000");
    db.exec("PRAGMA query_only = ON");
    // A query over a common word walks a lot of the file; a bigger cache and mapped reads keep it quick.
    db.exec("PRAGMA cache_size = -65536");
    db.exec("PRAGMA mmap_size = 536870912");
    return work(db);
  } finally {
    db.close();
  }
}

// ── Query text ────────────────────────────────────────────────────────────

const TERM = /"([^"]*)"(\*?)|([^\s"]+)/g;
const WORD_CHAR = /[\p{L}\p{N}_]/u;
const WORDS = /[\p{L}\p{N}_]+/gu;

/**
 * Typed text as an FTS5 expression that can only mean words. Every word or "phrase" is quoted
 * (quotes delimit, so none occurs inside), which turns AND, OR, NOT, NEAR, colons and brackets
 * into plain text. A * after a word or phrase makes its last word a prefix, if that word has two
 * letters or more. Words are ANDed, or ORed with match "any". Empty when nothing is searchable.
 */
export function ftsQuery(text: string, match: "all" | "any" = "all"): string {
  const terms: string[] = [];
  const found = [...text.replaceAll("\0", " ").matchAll(TERM)].slice(0, MAX_TERMS * 2);
  for (const m of found) {
    const phrase = m[1] ?? "";
    let body = (phrase || m[3] || "").trim();
    let prefix = Boolean(m[2]);
    if (!phrase && body.endsWith("*")) {
      body = body.replace(/\*+$/, "");
      prefix = true;
    }
    body = Array.from(body).slice(0, MAX_TERM_CHARS).join("");
    if (!WORD_CHAR.test(body)) continue;
    const last = body.match(WORDS)?.at(-1) ?? "";
    terms.push(`"${body}"${prefix && Array.from(last).length >= 2 ? "*" : ""}`);
  }
  return terms.slice(0, MAX_TERMS).join(match === "any" ? " OR " : " ");
}

/** A date (YYYY-MM-DD) as the timestamp to compare ts with; an end date takes in its whole day. */
function bound(day: string | null, end = false): string | null {
  if (!day) return null;
  const t = Date.parse(`${day}T00:00:00Z`);
  if (Number.isNaN(t)) return null;
  return `${new Date(t + (end ? 86_400_000 : 0)).toISOString().slice(0, 10)}T00:00:00Z`;
}

// ── Search ────────────────────────────────────────────────────────────────

export interface SearchParams {
  q: string;
  sources: string[];
  who: string;
  since: string | null;
  until: string | null;
  limit: number;
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
const SOURCE_NAME = /^[A-Za-z0-9_.-]{1,40}$/;
export const MAX_QUERY_CHARS = 200;

/** Query-string parameters as search parameters, or the reason they won't do. */
export function parseSearch(p: URLSearchParams): { params: SearchParams } | { error: string } {
  const q = (p.get("q") ?? "").trim();
  const who = (p.get("who") ?? "").trim();
  if (q.length > MAX_QUERY_CHARS || who.length > MAX_QUERY_CHARS) return { error: "query too long" };
  const sources = (p.get("source") ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  if (sources.length > 30 || sources.some((s) => !SOURCE_NAME.test(s))) return { error: "bad source" };
  const day = (name: string) => {
    const v = p.get(name);
    return v ? v : null;
  };
  const since = day("since");
  const until = day("until");
  if ((since && !ISO_DAY.test(since)) || (until && !ISO_DAY.test(until))) return { error: "bad date" };
  const asked = Number(p.get("limit") ?? 50);
  const limit = Number.isInteger(asked) ? Math.min(Math.max(asked, 1), 100) : 50;
  return { params: { q, sources, who, since, until, limit } };
}

function toHit(r: Record<string, unknown>): MemoryHit {
  const text = String(r.in_text ?? "");
  const title = String(r.in_title ?? "");
  return {
    id: String(r.id),
    source: String(r.source),
    stream: String(r.stream),
    ts: String(r.ts),
    who: String(r.who),
    where_: String(r.where_),
    title: String(r.title),
    snippet: [text, title].find((s) => s.includes(MARK_START)) ?? text,
    score: Number(r.score),
    from_me: r.from_me === null || r.from_me === undefined ? null : Boolean(r.from_me),
  };
}

/** The best matches for the typed text, with how many rows each source has among all of them. */
export function searchMemory(p: SearchParams): MemorySearchResponse {
  const started = performance.now();
  let expression = ftsQuery(p.q);
  const ranked = expression !== "";
  const person = ftsQuery(p.who);
  if (expression && person) expression = `(${expression}) AND who : (${person})`;
  else if (person) expression = `who : (${person})`;

  const since = bound(p.since);
  const until = bound(p.until, true);
  const dates: string[] = [];
  const dateArgs: string[] = [];
  if (since) {
    dates.push("AND ts >= ?");
    dateArgs.push(since);
  }
  if (until) {
    dates.push("AND ts < ?");
    dateArgs.push(until);
  }

  const none: MemorySearchResponse = { indexed: false, query: p.q, hits: [], facets: [], total: null, took_ms: 0 };
  const response = withIndex<MemorySearchResponse>(none, (db) => {
    let facets: MemoryFacet[];
    if (expression) {
      facets = db
        .prepare(`SELECT source, count(*) AS n FROM mem WHERE mem MATCH ? ${dates.join(" ")} GROUP BY source`)
        .all(expression, ...dateArgs)
        .map((r) => ({ source: String(r.source), count: Number(r.n) }));
    } else {
      const where = dates.length ? `WHERE ${dates.join(" ").replace(/^AND /, "")}` : "";
      facets = db
        .prepare(`SELECT source, count(*) AS n FROM records ${where} GROUP BY source`)
        .all(...dateArgs)
        .map((r) => ({ source: String(r.source), count: Number(r.n) }));
    }
    facets.sort((a, b) => b.count - a.count || a.source.localeCompare(b.source));
    const chosen = p.sources.length ? facets.filter((f) => p.sources.includes(f.source)) : facets;
    const total = chosen.reduce((sum, f) => sum + f.count, 0);

    // With nothing to match on, filters alone list the newest rows they allow; no filters, no rows.
    let hits: MemoryHit[] = [];
    const sourceSql = p.sources.length ? `AND source IN (${p.sources.map(() => "?").join(",")})` : "";
    if (expression) {
      hits = db
        .prepare(
          `SELECT id, source, stream, ts, who, where_, title,
                  snippet(mem, 7, ?, ?, '…', ?) AS in_text, snippet(mem, 6, ?, ?, '…', ?) AS in_title,
                  bm25(mem, ${WEIGHTS}) AS score, from_me
           FROM mem WHERE mem MATCH ? ${sourceSql} ${dates.join(" ")}
           ORDER BY ${ranked ? "score, ts DESC" : "ts DESC"} LIMIT ?`,
        )
        .all(
          MARK_START,
          MARK_END,
          SNIPPET_TOKENS,
          MARK_START,
          MARK_END,
          SNIPPET_TOKENS,
          expression,
          ...p.sources,
          ...dateArgs,
          p.limit,
        )
        .map(toHit);
    } else if (p.sources.length || since || until) {
      const where = [sourceSql.replace(/^AND /, ""), ...dates.map((d) => d.replace(/^AND /, ""))].filter(Boolean);
      hits = db
        .prepare(
          `SELECT id, source, stream, ts, who, where_, title, text AS in_text, title AS in_title, 0 AS score, from_me
           FROM records ${where.length ? `WHERE ${where.join(" AND ")}` : ""} ORDER BY ts DESC LIMIT ?`,
        )
        .all(...p.sources, ...dateArgs, p.limit)
        .map((r) => toHit({ ...r, in_text: String(r.in_text ?? "").slice(0, 240), in_title: "" }));
    }
    return { indexed: true, query: p.q, hits, facets, total, took_ms: 0 };
  });
  return { ...response, took_ms: Math.round(performance.now() - started) };
}

// ── Context ───────────────────────────────────────────────────────────────

const CONTEXT_COLUMNS = "id, source, stream, ts, who, where_, title, text, from_me";
export const MAX_ID_CHARS = 600;

function toRecord(r: Record<string, unknown>, target: boolean): MemoryRecord {
  return {
    id: String(r.id),
    source: String(r.source),
    stream: String(r.stream),
    ts: String(r.ts),
    who: String(r.who),
    where_: String(r.where_),
    title: String(r.title),
    text: String(r.text),
    from_me: r.from_me === null || r.from_me === undefined ? null : Boolean(r.from_me),
    target,
  };
}

/**
 * The record and up to `before` and `after` of its neighbours in the same chat, channel or mail
 * thread (or the same source and day), oldest first. Null for an id the index doesn't have.
 * Same records as `twin.memory.context`, taken from the index instead of the month files.
 */
export function memoryContext(id: string, before = 10, after = 10): MemoryContextResponse | null {
  return withIndex<MemoryContextResponse | null>(null, (db) => {
    const row = db.prepare(`SELECT ${CONTEXT_COLUMNS}, thread FROM records WHERE id = ?`).get(id);
    if (!row) return null;
    const thread = String(row.thread);
    const ts = String(row.ts);
    const earlier = db
      .prepare(
        `SELECT ${CONTEXT_COLUMNS} FROM records WHERE thread = ? AND (ts < ? OR (ts = ? AND id < ?))
         ORDER BY ts DESC, id DESC LIMIT ?`,
      )
      .all(thread, ts, ts, id, before)
      .reverse();
    const later = db
      .prepare(
        `SELECT ${CONTEXT_COLUMNS} FROM records WHERE thread = ? AND (ts > ? OR (ts = ? AND id > ?))
         ORDER BY ts, id LIMIT ?`,
      )
      .all(thread, ts, ts, id, after);
    return {
      id,
      records: [
        ...earlier.map((r) => toRecord(r, false)),
        toRecord(row, true),
        ...later.map((r) => toRecord(r, false)),
      ],
    };
  });
}

// ── Recall ────────────────────────────────────────────────────────────────

const RECALL_KINDS: readonly RecallKind[] = ["event", "task", "feed", "person"];

function text(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function recallHit(raw: unknown): MemoryHit | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (!text(r.id) || !text(r.source)) return null;
  return {
    id: text(r.id),
    source: text(r.source),
    stream: text(r.stream),
    ts: text(r.ts),
    who: text(r.who),
    where_: text(r.where_),
    title: text(r.title),
    snippet: text(r.snippet),
    score: typeof r.score === "number" ? r.score : 0,
    from_me: typeof r.from_me === "boolean" ? r.from_me : null,
  };
}

function recallTrigger(raw: unknown): RecallTrigger | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const kind = RECALL_KINDS.find((k) => k === r.kind);
  if (!kind || !text(r.id) || !text(r.title) || !Array.isArray(r.memories)) return null;
  const memories = r.memories.map(recallHit).filter((h): h is MemoryHit => h !== null);
  if (memories.length === 0) return null;
  return { kind, id: text(r.id), title: text(r.title), when: text(r.when) || null, memories };
}

/** clones/recall/today.json: what the vault remembers about today's events, tasks, feed and people. */
export async function getRecall(): Promise<RecallResponse> {
  const now = new Date().toISOString();
  const file = path.join(vaultPath(), "clones", "recall", "today.json");
  let data: unknown;
  try {
    const stat = await fs.stat(file);
    if (stat.size > MAX_RECALL_BYTES) return { exists: false, generated: null, now, triggers: [] };
    data = JSON.parse(await fs.readFile(file, "utf8"));
  } catch {
    return { exists: false, generated: null, now, triggers: [] };
  }
  const d = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  const triggers = (Array.isArray(d.triggers) ? d.triggers : [])
    .map(recallTrigger)
    .filter((t): t is RecallTrigger => t !== null);
  return { exists: true, generated: text(d.generated) || null, now, triggers };
}
