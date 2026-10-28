"use client";

// The care view's data and actions, and how its items are grouped and ordered. Shared by the
// Care view and the Home card.

import { useCallback } from "react";

import { useToast } from "@/components/Toasts";

import { useFlash, useJson } from "./client";
import { daysBetween, localDay } from "./format";
import type { CareAction, CareItemView, CareResponse, CareWaitingOn } from "./types";

const SAVE_FAILED = "Couldn't save that. Is the vault reachable? Nothing was written.";

export const CARE_TOAST: Record<CareAction, string> = {
  done: "Marked done",
  waiting: "Marked waiting",
  not_relevant: "Marked not relevant",
};

async function sendCareFeedback(itemId: string, action: CareAction): Promise<void> {
  const res = await fetch("/api/care/feedback", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ item_id: itemId, action }),
    keepalive: true,
  });
  if (!res.ok) throw new Error(`/api/care/feedback returned ${res.status}`);
}

/** care.json and the three item actions. `onChange` runs after a mark lands. */
export function useCare(onChange?: () => void) {
  const { data, error, setData, setError } = useJson<CareResponse>("/api/care");
  const notify = useToast();
  const { flashId, flash } = useFlash();

  const act = useCallback(
    (item: CareItemView, action: CareAction) => {
      if (item.action === action) return;
      const set = (a: CareAction | null, at: string | null) =>
        setData((d) => (d ? { ...d, items: d.items.map((i) => (i.id === item.id ? { ...i, action: a, acted_at: at } : i)) } : d));
      flash(action === "done" ? "group:done" : item.id);
      set(action, new Date().toISOString());
      sendCareFeedback(item.id, action).then(
        () => {
          notify(CARE_TOAST[action], action === "done" ? "ok" : "info");
          onChange?.();
        },
        () => {
          set(item.action, item.acted_at);
          setError(SAVE_FAILED);
        },
      );
    },
    [setData, setError, flash, notify, onChange],
  );

  return { data, error, flashId, act, clearError: () => setError(null) };
}

/** Where an item sits once the reader's own mark is applied; null when they set it aside. */
export function careStatus(i: CareItemView): "open" | "waiting" | "done" | null {
  if (i.action === "not_relevant") return null;
  if (i.action === "done" || i.status === "done") return "done";
  if (i.action === "waiting") return "waiting";
  return i.status;
}

/** The groups of the open list, in order: the reader's move first, then who they wait on. */
export const CARE_GROUPS: readonly { id: CareWaitingOn; label: string; hint: string }[] = [
  { id: "me", label: "Your move", hint: "waiting on you" },
  { id: "provider", label: "Waiting on a provider", hint: "a clinic or doctor's office" },
  { id: "insurer", label: "Waiting on the insurer", hint: "" },
  { id: "other", label: "Waiting on someone else", hint: "" },
];

const byDue = (a: CareItemView, b: CareItemView) => (a.due ?? "9999-12-31").localeCompare(b.due ?? "9999-12-31");

export interface CareGroups {
  groups: Record<CareWaitingOn, CareItemView[]>;
  done: CareItemView[];
}

/**
 * Items by who the next move is with. One the reader marked waiting has left their hands, so it
 * moves from "Your move" to "Waiting on someone else" when it was theirs. Open before waiting,
 * then nearest due date first, in the order the clone listed them.
 */
export function groupCare(items: CareItemView[]): CareGroups {
  const groups: Record<CareWaitingOn, CareItemView[]> = { me: [], provider: [], insurer: [], other: [] };
  const done: CareItemView[] = [];
  for (const i of items) {
    const place = careStatus(i);
    if (place === null) continue;
    if (place === "done") done.push(i);
    else groups[place === "waiting" && i.waiting_on === "me" ? "other" : i.waiting_on].push(i);
  }
  for (const list of Object.values(groups)) {
    list.sort((a, b) => Number(careStatus(a) === "waiting") - Number(careStatus(b) === "waiting") || byDue(a, b));
  }
  done.sort((a, b) => (b.acted_at ?? "").localeCompare(a.acted_at ?? ""));
  return { groups, done };
}

/** The one item to show first: the reader's own move with the nearest due date, else what they wait on. */
export function mostUrgent(items: CareItemView[]): CareItemView | null {
  const { groups } = groupCare(items);
  const open = (list: CareItemView[]) => list.filter((i) => careStatus(i) === "open");
  return (
    open(groups.me)[0] ??
    [...open(groups.provider), ...open(groups.insurer), ...open(groups.other)].sort(byDue)[0] ??
    groups.provider[0] ??
    groups.insurer[0] ??
    groups.other[0] ??
    null
  );
}

/** How many items still ask something of the reader. */
export function yourMoves(items: CareItemView[]): number {
  return groupCare(items).groups.me.filter((i) => careStatus(i) === "open").length;
}

/** "Overdue · Oct 3", "Due today", "Due Oct 30", with how pressing it is. */
export function careDue(i: CareItemView, now: string): { text: string; tone: "bad" | "warn" | "muted" } | null {
  if (!i.due || careStatus(i) === "done") return null;
  const d = daysBetween(localDay(now), i.due);
  const date = new Date(`${i.due}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  if (d < 0) return { text: `Overdue · ${date}`, tone: "bad" };
  if (d === 0) return { text: "Due today", tone: "warn" };
  if (d === 1) return { text: "Due tomorrow", tone: "warn" };
  if (d <= 3) return { text: `Due in ${d} days`, tone: "warn" };
  return { text: `Due ${date}`, tone: "muted" };
}

/** The first sentence of a summary, for a one-line status. */
export function firstSentence(text: string): string {
  const t = text.trim();
  const m = t.match(/^[\s\S]+?[.!?](?=\s+[A-Z"'(]|\s*$)/);
  return (m ? m[0] : t).trim();
}

/** Put text on the clipboard. Falls back to a hidden textarea where the async API isn't allowed. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.cssText = "position:fixed;top:0;left:0;opacity:0";
    document.body.appendChild(area);
    area.select();
    try {
      return document.execCommand("copy");
    } catch {
      return false;
    } finally {
      area.remove();
    }
  }
}
