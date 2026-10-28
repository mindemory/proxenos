// Server-side access to the care clone's output (vault/clones/care/care.json) and the reader's
// marks on its items (clones/care/feedback.jsonl). Import only from route handlers.
//
// care.json is written by `proxenos clone care` and only read here. Every field is checked, so a
// hand-edited or half-written file shows what it can instead of taking the page down. The page
// never sees the records behind the evidence: only their memory ids, source and time.

import path from "node:path";

import type {
  CareAction,
  CareCited,
  CareEvent,
  CareEventKind,
  CareItem,
  CareItemKind,
  CareItemView,
  CareResponse,
  CareScript,
  CareScriptKind,
  CareStatus,
  CareWaitingOn,
} from "./types";
import { CARE_ACTIONS } from "./types";
import { appendJsonl, foldLog, nowIso, readJsonFile, vaultInfo, vaultPath } from "./vault";

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
const MAX_LIST = 500;

const EVENT_KINDS: readonly CareEventKind[] = [
  "symptom",
  "visit",
  "test",
  "result",
  "referral",
  "call",
  "message",
  "bill",
  "claim",
  "records",
  "prescription",
];
const ITEM_KINDS: readonly CareItemKind[] = [
  "appointment",
  "referral",
  "bill",
  "claim",
  "records",
  "prescription",
  "form",
  "follow_up",
  "question",
];
const WAITING_ON: readonly CareWaitingOn[] = ["me", "provider", "insurer", "other"];
const STATUSES: readonly CareStatus[] = ["open", "waiting", "done"];
const SCRIPT_KINDS: readonly CareScriptKind[] = ["call", "email", "portal_message", "form"];

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function oneOf<T extends string>(v: unknown, values: readonly T[]): T | null {
  return typeof v === "string" && values.includes(v as T) ? (v as T) : null;
}

function ids(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string").slice(0, 50) : [];
}

function record(raw: unknown): Record<string, unknown> | null {
  return raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : null;
}

function toEvent(raw: unknown): CareEvent | null {
  const r = record(raw);
  const kind = oneOf(r?.kind, EVENT_KINDS);
  const date = str(r?.date);
  if (!r || !kind || !str(r.id) || !str(r.title).trim() || !ISO_DAY.test(date)) return null;
  return {
    id: str(r.id),
    date,
    kind,
    title: str(r.title).trim(),
    detail: str(r.detail),
    with: str(r.with).trim(),
    evidence: ids(r.evidence),
  };
}

function toItem(raw: unknown): CareItem | null {
  const r = record(raw);
  if (!r || !str(r.id) || !str(r.title).trim()) return null;
  const due = str(r.due);
  return {
    id: str(r.id),
    title: str(r.title).trim(),
    kind: oneOf(r.kind, ITEM_KINDS) ?? "follow_up",
    waiting_on: oneOf(r.waiting_on, WAITING_ON) ?? "me",
    next_step: str(r.next_step),
    due: ISO_DAY.test(due) ? due : null,
    status: oneOf(r.status, STATUSES) ?? "open",
    evidence: ids(r.evidence),
  };
}

function toScript(raw: unknown): CareScript | null {
  const r = record(raw);
  const kind = oneOf(r?.kind, SCRIPT_KINDS);
  if (!r || !kind || !str(r.id) || !str(r.item_id) || !str(r.body).trim()) return null;
  return { id: str(r.id), item_id: str(r.item_id), kind, title: str(r.title).trim(), body: str(r.body).trim() };
}

function unique<T extends { id: string }>(raws: unknown, parse: (raw: unknown) => T | null): T[] {
  const seen = new Set<string>();
  const out: T[] = [];
  for (const raw of Array.isArray(raws) ? raws.slice(0, MAX_LIST) : []) {
    const x = parse(raw);
    if (!x || seen.has(x.id)) continue;
    seen.add(x.id);
    out.push(x);
  }
  return out;
}

function citedOf(raw: unknown): Record<string, CareCited> {
  const out: Record<string, CareCited> = {};
  for (const [key, value] of Object.entries(record(raw) ?? {})) {
    const v = record(value);
    if (v && str(v.source) && str(v.ts)) out[key] = { source: str(v.source), ts: str(v.ts) };
  }
  return out;
}

function countsOf(raw: unknown): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [key, value] of Object.entries(record(raw) ?? {})) {
    if (typeof value === "number" && Number.isFinite(value) && value >= 0) out[key] = value;
  }
  return out;
}

/** care.json with each item's latest mark from the page folded in. */
export async function getCare(): Promise<CareResponse> {
  const vault = vaultPath();
  const dir = path.join(vault, "clones", "care");
  const doc = record(await readJsonFile(path.join(dir, "care.json")));
  const acted = await foldLog<CareAction>(path.join(dir, "feedback.jsonl"), "item_id", CARE_ACTIONS);

  const items: CareItemView[] = unique(doc?.open_items, toItem).map((item) => {
    const a = acted.get(item.id);
    return { ...item, action: a?.action ?? null, acted_at: a?.ts ?? null };
  });
  const live = new Set(items.map((i) => i.id));

  return {
    now: nowIso(),
    vault: await vaultInfo(vault),
    exists: doc !== null,
    generated: str(doc?.generated) || null,
    summary: str(doc?.summary),
    timeline: unique(doc?.timeline, toEvent).sort((a, b) => a.date.localeCompare(b.date)),
    items,
    scripts: unique(doc?.scripts, toScript).filter((s) => live.has(s.item_id)),
    visit_brief: str(doc?.visit_brief),
    cited: citedOf(doc?.cited),
    records: countsOf(doc?.records),
  };
}

/** One line in clones/care/feedback.jsonl, which the next run applies. The file is 0600. */
export async function appendCareFeedback(itemId: string, action: CareAction) {
  const entry = { item_id: itemId, action, ts: nowIso() };
  await appendJsonl(["clones", "care", "feedback.jsonl"], entry);
  return entry;
}
