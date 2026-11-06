// How drafts are grouped, labelled and ordered. Shared by the Drafts view, the Home
// card and the server, so none of them has to know every value `for` or `kind` can take.

import type { Draft, DraftReviews, Errand, ErrandMessage } from "./types";

/** The groups, in the order the Drafts view shows them. */
export const DRAFT_GROUPS: readonly { id: string; label: string }[] = [
  { id: "ask", label: "From Ask" },
  { id: "reply", label: "Replies" },
  { id: "task", label: "Tasks" },
  { id: "care", label: "Care" },
  { id: "choice", label: "This week's choices" },
  { id: "jobs", label: "Jobs" },
  { id: "outreach", label: "Outreach" },
  { id: "project", label: "Projects" },
  { id: "reading", label: "Reading notes" },
];

export const OTHER_GROUP = { id: "other", label: "Other" };

export const KIND_LABELS: Record<string, string> = {
  reply: "Reply",
  email: "Email",
  doc: "Doc",
  plan: "Plan",
  checklist: "Checklist",
  blocked: "Blocked",
};

/** Statuses that settle a draft: the reader's, and overtaken, when the messages made it moot. */
const SETTLED = new Set(["discarded", "sent", "overtaken"]);

/** Waiting for the reader to send: not sent, discarded or overtaken. An approved draft that hasn't gone out still waits. */
export function isAwaiting(status: string): boolean {
  return !SETTLED.has(status);
}

const NOTE_KINDS = new Set(["doc", "checklist", "plan", "note"]);

/** Kept for the reader, not sent to anyone: a doc, plan, checklist or note addressed to no one. */
export function isNote(d: Pick<Draft, "kind" | "to">): boolean {
  return NOTE_KINDS.has(d.kind) && !d.to.trim();
}

/** Days a draft can sit unchanged before it's folded away as older. */
export const STALE_DAYS = 3;

/** Not changed for STALE_DAYS: not drafted again, edited or acted on since. */
export function isStale(d: Draft, now: number): boolean {
  const changed = Math.max(d.created ? Date.parse(d.created) || 0 : 0, d.updated ? Date.parse(d.updated) || 0 : 0);
  return now - changed > STALE_DAYS * 24 * 60 * 60 * 1000;
}

/** Days an unbacked draft can wait before it's asked about. */
export const CHECK_DAYS = 7;

/**
 * A message no thread backs (a project's or Ask's draft: none of its chat is known) that has waited
 * CHECK_DAYS unchanged: nothing will ever show it was handled, so the reader is asked.
 */
export function needsCheck(d: Draft, now: number): boolean {
  if (!isAwaiting(d.status) || isNote(d) || d.thread) return false;
  const changed = Math.max(d.created ? Date.parse(d.created) || 0 : 0, d.updated ? Date.parse(d.updated) || 0 : 0);
  return now - changed > CHECK_DAYS * 24 * 60 * 60 * 1000;
}

/** A message or post still to go out, and recent: what asks for the reader on the home page and the top bar. */
export function isToSend(d: Draft, now: number): boolean {
  return isAwaiting(d.status) && !isNote(d) && !isStale(d, now);
}

/** Still the reader's to act on: not sent, discarded or overtaken. */
export function isLive(status: string): boolean {
  return !SETTLED.has(status);
}

/** A value from the file as text for a badge: known labels as written, anything else tidied. */
export function kindLabel(kind: string): string {
  if (KIND_LABELS[kind]) return KIND_LABELS[kind];
  const text = kind.replace(/[_-]+/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1, 24) : "Draft";
}

export function channelLabel(channel: string): string {
  if (channel === "in_person") return "In person";
  if (channel === "whatsapp") return "WhatsApp";
  if (channel === "wechat") return "WeChat";
  const text = channel.replace(/[_-]+/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1, 24) : "";
}

export interface DraftGroup {
  id: string;
  label: string;
  drafts: Draft[];
}

const createdMs = (d: Draft) => (d.created ? Date.parse(d.created) || 0 : 0);

/**
 * Drafts grouped by what they're for: Replies, Tasks, Care, Outreach, Projects, Reading notes, then
 * "Other" for any other value (or none), so a draft never goes missing for being new.
 * Each group lists the ones waiting first, newest first.
 */
export function groupDrafts(drafts: Draft[]): DraftGroup[] {
  const known = new Set(DRAFT_GROUPS.map((g) => g.id));
  const groups = [...DRAFT_GROUPS, OTHER_GROUP].map((g) => ({
    ...g,
    drafts: drafts.filter((d) => (g.id === OTHER_GROUP.id ? !known.has(d.for) : d.for === g.id)),
  }));
  for (const g of groups) {
    g.drafts.sort((a, b) => Number(isAwaiting(b.status)) - Number(isAwaiting(a.status)) || createdMs(b) - createdMs(a));
  }
  return groups.filter((g) => g.drafts.length > 0);
}

/** One of an errand's messages still waiting on the reader: ready to send, or waiting for an address. */
export interface ErrandItem {
  errand: Errand;
  index: number;
  message: ErrandMessage;
}

/** The messages of errands that wait on the reader: not sent, set aside, or of an errand dropped or still working. */
export function openErrandItems(errands: readonly Errand[]): ErrandItem[] {
  return errands.flatMap((errand) =>
    errand.status === "ready" || errand.status === "waiting"
      ? errand.messages.flatMap((message, index) =>
          message.state === "ready" || message.state === "waiting" ? [{ errand, index, message }] : [],
        )
      : [],
  );
}

/** Days an errand's message waits in the main list: an errand is one ask, sent soon or done another way. */
export const ERRAND_STALE_DAYS = 1;

/** An errand message left ERRAND_STALE_DAYS since its errand last changed: folded away as older. */
export function isStaleErrand(item: ErrandItem, now: number): boolean {
  const changed = Math.max(Date.parse(item.errand.created) || 0, Date.parse(item.errand.updated) || 0);
  return now - changed > ERRAND_STALE_DAYS * 24 * 60 * 60 * 1000;
}

/** Whether two recipient lines name one person: the same name, or a first name alone and a full name it begins. */
export function samePerson(a: string, b: string): boolean {
  const x = a.toLowerCase().split(/\s+/).filter(Boolean);
  const y = b.toLowerCase().split(/\s+/).filter(Boolean);
  if (x.length === 0 || y.length === 0) return false;
  return x.join(" ") === y.join(" ") || ((x.length === 1 || y.length === 1) && x[0] === y[0]);
}

/** One thing waiting to be sent: a draft or an errand's message, with what it's the same as folded under it. */
export type Waiting =
  | { kind: "draft"; draft: Draft; under: ErrandItem | null }
  | { kind: "errand"; item: ErrandItem; under: Draft | null };

/**
 * Everything waiting to be sent, each thing once: the drafts to send (isToSend) and the errands'
 * messages. An errand message and a draft to the same person on the same channel are the same thing
 * waiting, so they make one card, the newer of the two, with the other folded under it. The server
 * counts the same way (proxenos.notify), and so do the Home counts.
 */
export function waitingToSend(drafts: readonly Draft[], items: readonly ErrandItem[]): Waiting[] {
  const free = [...drafts];
  const out: Waiting[] = [];
  for (const item of items) {
    const at = free.findIndex((d) => d.channel === item.message.channel && samePerson(d.to, item.message.to));
    if (at === -1) {
      out.push({ kind: "errand", item, under: null });
      continue;
    }
    const [twin] = free.splice(at, 1);
    const itemMs = Date.parse(item.errand.created) || 0;
    out.push(itemMs >= createdMs(twin) ? { kind: "errand", item, under: twin } : { kind: "draft", draft: twin, under: item });
  }
  for (const draft of free) out.push({ kind: "draft", draft, under: null });
  return out;
}

/** The roadmap's gate looks at the last two weeks of reviews. */
export const REVIEW_WINDOW_DAYS = 14;

const DAY_MS = 24 * 60 * 60 * 1000;

interface Fate {
  edited: boolean;
  decision: "approve" | "discard" | null;
  sent: boolean;
  at: number; // newest entry for this draft, ms
}

/**
 * clones/drafts/feedback.jsonl folded per draft into what became of each one reviewed. File order
 * wins, so a later approve undoes a discard. A draft marked sent counts as approved, since
 * sending it is the strongest approval there is. How much an edit changed isn't logged, so any
 * edit counts as a light one.
 */
export function foldReviews(entries: readonly unknown[], now: number = Date.now()): DraftReviews {
  const fates = new Map<string, Fate>();
  let copied = 0;
  let last: string | null = null;
  for (const e of entries) {
    if (!e || typeof e !== "object") continue;
    const r = e as Record<string, unknown>;
    const id = typeof r.draft_id === "string" ? r.draft_id : "";
    const action = typeof r.action === "string" ? r.action : "";
    const ts = typeof r.ts === "string" ? r.ts : "";
    if (!id || !action) continue;
    if (action === "copy") {
      copied++;
      continue;
    }
    if (action !== "edit" && action !== "approve" && action !== "discard" && action !== "sent") continue;
    const fate = fates.get(id) ?? { edited: false, decision: null, sent: false, at: 0 };
    if (action === "edit") fate.edited = true;
    else if (action === "sent") {
      fate.sent = true;
      fate.decision = "approve";
    } else fate.decision = action;
    const at = Date.parse(ts);
    if (!Number.isNaN(at)) fate.at = Math.max(fate.at, at);
    fates.set(id, fate);
    if (ts && (!last || ts > last)) last = ts;
  }

  const cutoff = now - REVIEW_WINDOW_DAYS * DAY_MS;
  let approved = 0;
  let edited = 0;
  let discarded = 0;
  let sent = 0;
  let recentReviewed = 0;
  let recentAccepted = 0;
  for (const f of fates.values()) {
    const accepted = f.decision !== "discard";
    if (f.decision === "discard") discarded++;
    else if (f.edited) edited++;
    else approved++; // every fate has an edit or a decision, so this one was approved
    if (f.sent) sent++;
    if (f.at >= cutoff) {
      recentReviewed++;
      if (accepted) recentAccepted++;
    }
  }
  return {
    reviewed: approved + edited + discarded,
    approved,
    edited,
    discarded,
    sent,
    copied,
    last,
    recentReviewed,
    recentAccepted,
  };
}
