// How drafts are grouped, labelled and ordered. Shared by the Drafts view, the Home
// card and the server, so none of them has to know every value `for` or `kind` can take.

import type { Draft, DraftReviews } from "./types";

/** The groups, in the order the Drafts view shows them. */
export const DRAFT_GROUPS: readonly { id: string; label: string }[] = [
  { id: "ask", label: "From Ask" },
  { id: "reply", label: "Replies" },
  { id: "task", label: "Tasks" },
  { id: "care", label: "Care" },
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

/** Waiting for the reader: not approved, discarded or sent. */
export function isAwaiting(status: string): boolean {
  return status !== "approved" && status !== "discarded" && status !== "sent";
}

/** Still the reader's to act on: neither sent nor discarded. */
export function isLive(status: string): boolean {
  return status !== "discarded" && status !== "sent";
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
