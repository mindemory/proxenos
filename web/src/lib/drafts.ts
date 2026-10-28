// How drafts are grouped, labelled and ordered. Shared by the Drafts view, the Home
// card and the server, so none of them has to know every value `for` or `kind` can take.

import type { Draft } from "./types";

/** The groups, in the order the Drafts view shows them. */
export const DRAFT_GROUPS: readonly { id: string; label: string }[] = [
  { id: "task", label: "Tasks" },
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

/** Waiting for the reader: not approved and not discarded. */
export function isAwaiting(status: string): boolean {
  return status !== "approved" && status !== "discarded";
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
 * Drafts grouped by what they're for: Tasks, Outreach, Projects, Reading notes, then
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
