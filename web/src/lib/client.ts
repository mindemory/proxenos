"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "@/components/Toasts";

import type {
  Action,
  AdviceAction,
  AdviceResponse,
  FeedItem,
  HomeResponse,
  ItemsResponse,
  NetworkAction,
  NetworkResponse,
  Reaction,
  SuggestionView,
  TaskAction,
  TasksResponse,
  TaskView,
} from "./types";

export const POLL_MS = 5 * 60 * 1000;

const SAVE_FAILED = "Couldn't save that. Is the vault reachable? Nothing was written.";

export async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`${url} returned ${res.status}`);
  return (await res.json()) as T;
}

async function postJson(url: string, body: object): Promise<void> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    keepalive: true,
  });
  if (!res.ok) throw new Error(`${url} returned ${res.status}`);
}

export function sendFeedback(itemId: string, action: Action): Promise<void> {
  return postJson("/api/feedback", { item_id: itemId, action });
}

export function sendTaskFeedback(taskId: string, action: TaskAction): Promise<void> {
  return postJson("/api/tasks/feedback", { task_id: taskId, action });
}

export function sendNetworkFeedback(itemId: string, action: NetworkAction): Promise<void> {
  return postJson("/api/network/feedback", { item_id: itemId, action });
}

export function sendAdviceFeedback(suggestionId: string, action: AdviceAction): Promise<void> {
  return postJson("/api/advice/feedback", { suggestion_id: suggestionId, action });
}

// Toast text for each action, written as what just happened.
export const REACTION_TOAST: Record<Reaction, string> = {
  useful: "Marked useful",
  not_me: "Marked not for you",
  save: "Saved",
};
export const TASK_TOAST: Record<TaskAction, string> = {
  done: "Task marked done",
  not_mine: "Marked not yours",
  dismiss: "Task dismissed",
};
export const ADVICE_TOAST: Record<AdviceAction, string> = {
  useful: "Marked useful",
  not_me: "Marked not you",
  doing: "Noted: you're doing it",
};

export const NETWORK_TOAST: Record<NetworkAction, string> = {
  useful: "Marked useful",
  not_me: "Marked not for you",
  done: "Marked done",
};

export function withReaction(items: FeedItem[], id: string, reaction: Reaction | null): FeedItem[] {
  return items.map((it) => (it.id === id ? { ...it, reaction } : it));
}

export function withOpened(items: FeedItem[], id: string): FeedItem[] {
  return items.map((it) => (it.id === id ? { ...it, opened: true } : it));
}

function withTaskAction(tasks: TaskView[], id: string, action: TaskAction | null, at: string | null): TaskView[] {
  return tasks.map((t) => (t.id === id ? { ...t, action, acted_at: at } : t));
}

function withAdviceAction<T extends SuggestionView | null>(s: T, id: string, action: AdviceAction | null, at: string | null): T {
  return s && s.id === id ? { ...s, action, acted_at: at } : s;
}

/** Highlight one row for a moment after an action touches it. */
export function useFlash() {
  const [flashId, setFlashId] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const flash = useCallback((id: string) => {
    window.clearTimeout(timer.current);
    setFlashId(id);
    timer.current = window.setTimeout(() => setFlashId(null), 1500);
  }, []);
  return { flashId, flash };
}

/** Fetch JSON once per mount (and again whenever `url` changes). */
export function useJson<T>(url: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    getJson<T>(url).then(
      (d) => {
        if (!alive) return;
        setData(d);
        setError(null);
      },
      (e: unknown) => alive && setError(String(e)),
    );
    return () => {
      alive = false;
    };
  }, [url]);
  return { data, error, setData, setError };
}

type Patch = (items: FeedItem[]) => FeedItem[];

/**
 * Items and card actions shared by the Feed and Saved views. With `poll`, it
 * re-checks every five minutes and holds a newer batch in `pending` until
 * the reader asks for it, so cards don't move under the cursor.
 */
export function useItems(url: string, poll = false) {
  const [data, setData] = useState<ItemsResponse | null>(null);
  const [pending, setPending] = useState<ItemsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const notify = useToast();
  const { flashId, flash } = useFlash();
  // Batch currently on screen; undefined until the first load.
  const shownBatch = useRef<string | null | undefined>(undefined);

  const accept = useCallback((next: ItemsResponse) => {
    shownBatch.current = next.latest?.batch ?? null;
    setData(next);
    setPending(null);
  }, []);

  const load = useCallback(
    (force: boolean) =>
      getJson<ItemsResponse>(url).then(
        (next) => {
          setError(null);
          const shown = shownBatch.current;
          if (force || !shown || !next.latest || next.latest.batch === shown) accept(next);
          else setPending(next);
        },
        (e: unknown) => setError(String(e)),
      ),
    [url, accept],
  );

  useEffect(() => {
    load(true);
    if (!poll) return;
    const timer = setInterval(() => load(false), POLL_MS);
    return () => clearInterval(timer);
  }, [load, poll]);

  const patch = useCallback((fn: Patch) => {
    setData((d) => (d ? { ...d, items: fn(d.items) } : d));
    setPending((p) => (p ? { ...p, items: fn(p.items) } : p));
  }, []);

  const react = useCallback(
    (item: FeedItem, reaction: Reaction) => {
      if (item.reaction === reaction) return;
      flash(item.id);
      patch((items) => withReaction(items, item.id, reaction));
      sendFeedback(item.id, reaction).then(
        () => notify(REACTION_TOAST[reaction], reaction === "useful" ? "ok" : "info"),
        () => {
          patch((items) => withReaction(items, item.id, item.reaction));
          setError(SAVE_FAILED);
        },
      );
    },
    [patch, flash, notify],
  );

  const open = useCallback(
    (item: FeedItem) => {
      patch((items) => withOpened(items, item.id));
      sendFeedback(item.id, "open").catch(() => {
        // Opening still works; only the log line is lost.
      });
    },
    [patch],
  );

  const showPending = useCallback(() => {
    if (pending) accept(pending);
  }, [pending, accept]);

  return {
    data,
    pending,
    error,
    flashId,
    clearError: () => setError(null),
    refresh: () => load(true),
    check: () => load(false),
    showPending,
    react,
    open,
  };
}

/** tasks.json and the three task actions. `onChange` runs after a write lands. */
export function useTasks(onChange?: () => void) {
  const { data, error, setData, setError } = useJson<TasksResponse>("/api/tasks");
  const notify = useToast();
  const { flashId, flash } = useFlash();

  const act = useCallback(
    (task: TaskView, action: TaskAction) => {
      const set = (a: TaskAction | null, at: string | null) =>
        setData((d) => (d ? { ...d, tasks: withTaskAction(d.tasks, task.id, a, at) } : d));
      set(action, new Date().toISOString());
      // A done task moves into the collapsed group; mark the group so the move is visible.
      if (action === "done") flash("group:done");
      sendTaskFeedback(task.id, action).then(
        () => {
          notify(TASK_TOAST[action], action === "done" ? "ok" : "info");
          onChange?.();
        },
        () => {
          set(task.action, task.acted_at);
          setError(SAVE_FAILED);
        },
      );
    },
    [setData, setError, flash, notify, onChange],
  );

  return { data, error, flashId, act, clearError: () => setError(null) };
}

/** One day of advice (null: the newest) and the three advice actions. */
export function useAdvice(date: string | null, onChange?: () => void) {
  const { data, error, setData, setError } = useJson<AdviceResponse>(
    date ? `/api/advice?date=${encodeURIComponent(date)}` : "/api/advice",
  );
  const notify = useToast();
  const { flashId, flash } = useFlash();

  const react = useCallback(
    (s: SuggestionView, action: AdviceAction) => {
      if (s.action === action) return;
      const set = (a: AdviceAction | null, at: string | null) =>
        setData((d) => (d ? { ...d, suggestions: d.suggestions.map((x) => withAdviceAction(x, s.id, a, at)) } : d));
      flash(s.id);
      set(action, new Date().toISOString());
      sendAdviceFeedback(s.id, action).then(
        () => {
          notify(ADVICE_TOAST[action], action === "not_me" ? "info" : "ok");
          onChange?.();
        },
        () => {
          set(s.action, s.acted_at);
          setError(SAVE_FAILED);
        },
      );
    },
    [setData, setError, flash, notify, onChange],
  );

  return { data, error, flashId, react, clearError: () => setError(null) };
}

type Idea = { id: string; action: NetworkAction | null; acted_at: string | null };

function withIdeaAction(ideas: NetworkResponse["ideas"], id: string, action: NetworkAction | null, at: string | null) {
  const f = <T extends Idea>(xs: T[]) => xs.map((x) => (x.id === id ? { ...x, action, acted_at: at } : x));
  return { ...ideas, projects: f(ideas.projects), outreach: f(ideas.outreach), to_read: f(ideas.to_read) };
}

/** People, projects, outreach and reading suggestions, with their three actions. */
export function useNetwork(onChange?: () => void) {
  const { data, error, setData, setError } = useJson<NetworkResponse>("/api/network");
  const notify = useToast();
  const { flashId, flash } = useFlash();

  const react = useCallback(
    (item: Idea, action: NetworkAction) => {
      if (item.action === action) return;
      const set = (a: NetworkAction | null, at: string | null) =>
        setData((d) => (d ? { ...d, ideas: withIdeaAction(d.ideas, item.id, a, at) } : d));
      flash(item.id);
      set(action, new Date().toISOString());
      sendNetworkFeedback(item.id, action).then(
        () => {
          notify(NETWORK_TOAST[action], action === "not_me" ? "info" : "ok");
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

  return { data, error, flashId, react, clearError: () => setError(null) };
}

// ── Last visit ──────────────────────────────────────────────────────────────

const VISIT_KEY = "twin.visit";
const VISIT_GAP_MS = 30 * 60 * 1000;

interface VisitRecord {
  last?: unknown; // ISO: when the page was last in use
  base?: unknown; // ISO or null: the baseline for the current visit
}

function readVisit(): VisitRecord {
  try {
    const v = JSON.parse(localStorage.getItem(VISIT_KEY) ?? "{}") as unknown;
    return v && typeof v === "object" ? (v as VisitRecord) : {};
  } catch {
    // Private window, blocked site data or a hand-edited value: treat as a first visit.
    return {};
  }
}

function writeVisit(v: { last: string; base: string | null }) {
  try {
    localStorage.setItem(VISIT_KEY, JSON.stringify(v));
  } catch {
    // Not remembering the visit only means the next brief counts from further back.
  }
}

/**
 * The "since you were last here" baseline. A visit is a run of activity with
 * gaps under 30 minutes, so reloading the page doesn't reset the brief.
 */
function visitBaseline(): string | null {
  const now = Date.now();
  const v = readVisit();
  const last = typeof v.last === "string" ? Date.parse(v.last) : NaN;
  let base: string | null = null;
  if (!Number.isNaN(last)) {
    if (now - last > VISIT_GAP_MS) base = new Date(last).toISOString();
    else if (typeof v.base === "string" && !Number.isNaN(Date.parse(v.base))) base = v.base;
  }
  writeVisit({ last: new Date(now).toISOString(), base });
  return base;
}

function touchVisit() {
  const v = readVisit();
  writeVisit({ last: new Date().toISOString(), base: typeof v.base === "string" ? v.base : null });
}

/** The opening brief, plus the task and advice actions it offers inline. */
export function useHome() {
  const [data, setData] = useState<HomeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const notify = useToast();
  const since = useRef<string | null | undefined>(undefined);

  const load = useCallback(() => {
    if (since.current === undefined) since.current = visitBaseline();
    const q = since.current ? `?since=${encodeURIComponent(since.current)}` : "";
    return getJson<HomeResponse>(`/api/home${q}`).then(
      (d) => {
        setError(null);
        setData(d);
      },
      (e: unknown) => setError(String(e)),
    );
  }, []);

  useEffect(() => {
    load();
    // Keep "last here" current while the tab stays open.
    const touch = () => document.visibilityState === "hidden" && touchVisit();
    document.addEventListener("visibilitychange", touch);
    window.addEventListener("pagehide", touchVisit);
    return () => {
      document.removeEventListener("visibilitychange", touch);
      window.removeEventListener("pagehide", touchVisit);
    };
  }, [load]);

  const actTask = useCallback(
    (task: TaskView, action: TaskAction) => {
      const set = (a: TaskAction | null, at: string | null) =>
        setData((d) =>
          d ? { ...d, tasks: { ...d.tasks, actionable: withTaskAction(d.tasks.actionable, task.id, a, at) } } : d,
        );
      set(action, new Date().toISOString());
      sendTaskFeedback(task.id, action).then(
        () => notify(TASK_TOAST[action], action === "done" ? "ok" : "info"),
        () => {
          set(task.action, task.acted_at);
          setError(SAVE_FAILED);
        },
      );
    },
    [notify],
  );

  const reactAdvice = useCallback(
    (s: SuggestionView, action: AdviceAction) => {
      if (s.action === action) return;
      const set = (a: AdviceAction | null, at: string | null, unanswered: number) =>
        setData((d) =>
          d ? { ...d, advice: { ...d.advice, unanswered, pick: withAdviceAction(d.advice.pick, s.id, a, at) } } : d,
        );
      const before = data?.advice.unanswered ?? 0;
      set(action, new Date().toISOString(), s.action === null ? Math.max(0, before - 1) : before);
      sendAdviceFeedback(s.id, action).then(
        () => notify(ADVICE_TOAST[action], action === "not_me" ? "info" : "ok"),
        () => {
          set(s.action, s.acted_at, before);
          setError(SAVE_FAILED);
        },
      );
    },
    [data, notify],
  );

  return { data, error, reload: load, actTask, reactAdvice, clearError: () => setError(null) };
}
