// Task grouping and urgency, shared by the Home brief, the Tasks view and the
// sidebar counts. Due dates are calendar days, so "today" is the reader's
// local date at the server's `now`.

import { daysBetween, localDay, shortDate } from "./format";
import type { TaskPriority, TaskView } from "./types";

export const PRIORITY_RANK: Record<TaskPriority, number> = { high: 0, medium: 1, low: 2 };

/** Days left until due soon stops being "later". Matches the warn colour. */
export const SOON_DAYS = 3;

export type Tone = "bad" | "warn" | "ok" | "muted";

/** Where a task sits once the reader's own actions are applied; null when it was set aside. */
export function placeOf(t: TaskView): "open" | "waiting" | "done" | null {
  if (t.action === "not_mine" || t.action === "dismiss") return null;
  if (t.action === "done" || t.status === "done") return "done";
  return t.status;
}

export function daysLeft(t: TaskView, today: string): number | null {
  return t.due ? daysBetween(today, t.due) : null;
}

export function isUrgent(t: TaskView, today: string): boolean {
  const d = daysLeft(t, today);
  return d !== null && d <= SOON_DAYS;
}

export function dueLabel(t: TaskView, now: string): { text: string; tone: Tone; title: string } | null {
  if (placeOf(t) === "done") return { text: "Done", tone: "ok", title: t.due ? `Was due ${shortDate(t.due, now)}` : "" };
  if (!t.due) return null;
  const d = daysBetween(localDay(now), t.due);
  const date = shortDate(t.due, now);
  if (d < 0) return { text: `Overdue · ${date}`, tone: "bad", title: `${-d} day${d === -1 ? "" : "s"} overdue` };
  if (d === 0) return { text: "Due today", tone: "warn", title: date };
  if (d === 1) return { text: "Due tomorrow", tone: "warn", title: date };
  if (d <= SOON_DAYS) return { text: `Due in ${d} days`, tone: "warn", title: date };
  return { text: `Due ${date}`, tone: "muted", title: `In ${d} days` };
}

const time = (iso: string | null) => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isNaN(t) ? Infinity : t;
};

const actedMs = (t: TaskView) => (time(t.acted_at) === Infinity ? 0 : time(t.acted_at));

// No due date sorts after every real one.
const byDue = (a: TaskView, b: TaskView) => (a.due ?? "9999-12-31").localeCompare(b.due ?? "9999-12-31");
const byPriority = (a: TaskView, b: TaskView) => PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority];
const byAsked = (a: TaskView, b: TaskView) => time(a.asked_at) - time(b.asked_at);

export interface TaskGroups {
  urgent: TaskView[]; // open, overdue or due within SOON_DAYS, soonest first
  open: TaskView[]; // the rest of open, high priority first
  waiting: TaskView[]; // waiting on someone else
  done: TaskView[]; // done, most recently acted on first
}

export function groupTasks(tasks: TaskView[], now: string): TaskGroups {
  const today = localDay(now);
  const g: TaskGroups = { urgent: [], open: [], waiting: [], done: [] };
  for (const t of tasks) {
    const place = placeOf(t);
    if (place === "open") (isUrgent(t, today) ? g.urgent : g.open).push(t);
    else if (place === "waiting") g.waiting.push(t);
    else if (place === "done") g.done.push(t);
  }
  g.urgent.sort((a, b) => byDue(a, b) || byPriority(a, b) || byAsked(a, b));
  g.open.sort((a, b) => byPriority(a, b) || byDue(a, b) || byAsked(a, b));
  g.waiting.sort((a, b) => byDue(a, b) || byAsked(a, b));
  g.done.sort((a, b) => actedMs(b) - actedMs(a));
  return g;
}

/** Open tasks in the order the brief shows them: urgent first, then by priority. */
export function byUrgency(tasks: TaskView[], now: string): TaskView[] {
  const g = groupTasks(tasks, now);
  return [...g.urgent, ...g.open];
}
