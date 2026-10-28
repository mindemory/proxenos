"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "@/components/Toasts";

import { markdownFile, openText } from "./actions";
import type {
  Action,
  AdviceAction,
  AdviceResponse,
  Draft,
  DraftAction,
  DraftReviews,
  DraftsViewResponse,
  FeedItem,
  HomeResponse,
  ItemsResponse,
  NetworkAction,
  NetworkResponse,
  PeopleEdit,
  PeopleEditResult,
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

/** keepalive lets a feedback line land even as the page closes, but caps the body at 64 KB. */
async function postJson(url: string, body: object, keepalive = true): Promise<void> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    keepalive,
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

/** A POST whose answer matters. No keepalive: it can wait for a rebuild. */
async function postForJson<T>(url: string, body: object): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${url} returned ${res.status}`);
  return (await res.json()) as T;
}

/**
 * Without keepalive: an edit can be longer than a keepalive request may carry. Resolves with
 * the review record as it stands once the action is saved, or null if the server couldn't say.
 */
export async function sendDraftAction(draftId: string, action: DraftAction, body?: string): Promise<DraftReviews | null> {
  const res = await postForJson<{ record?: DraftReviews | null }>("/api/drafts/feedback", { draft_id: draftId, action, body });
  return res.record ?? null;
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

export const DRAFT_TOAST: Record<DraftAction, string> = {
  approve: "Approved. Nothing was sent: open it when you're ready",
  discard: "Draft discarded",
  edit: "Draft saved",
  copy: "Copied to the clipboard",
  opened: "Opened",
  sent: "Marked sent",
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

  /** Fetch the index again, as after a rebuild. */
  const reload = useCallback(
    () =>
      getJson<NetworkResponse>("/api/network").then(
        (d) => setData(d),
        (e: unknown) => setError(String(e)),
      ),
    [setData, setError],
  );

  /** Say who is who, then show the rebuilt index; a failed rebuild keeps the edit for the next. */
  const editPerson = useCallback(
    async (action: PeopleEdit, id: string, other?: { id: string } | { name: string }): Promise<PeopleEditResult> => {
      let result: PeopleEditResult;
      try {
        const body = { action, id, ...(other && "id" in other ? { other: other.id } : other) };
        result = await postForJson<PeopleEditResult>("/api/network/people", body);
      } catch {
        notify("Couldn't save that. Nothing was changed.", "info");
        return { ok: false, saved: false, rebuilt: false, message: "Couldn't save that." };
      }
      if (result.rebuilt) {
        await reload();
        notify(PEOPLE_TOAST[action], "ok");
      } else {
        notify("Saved, applies on the next refresh", "info");
      }
      return result;
    },
    [notify, reload],
  );

  /** Rebuild people.json now, with every saved edit. */
  const refreshPeople = useCallback(async (): Promise<PeopleEditResult> => {
    let result: PeopleEditResult;
    try {
      result = await postForJson<PeopleEditResult>("/api/network/refresh", {});
    } catch {
      result = { ok: false, saved: false, rebuilt: false, message: "Couldn't reach the server." };
    }
    if (result.rebuilt) {
      await reload();
      notify("People index rebuilt", "ok");
    } else {
      notify(result.message || "The rebuild didn't finish", "info");
    }
    return result;
  }, [notify, reload]);

  return { data, error, flashId, react, editPerson, refreshPeople, clearError: () => setError(null) };
}

export const PEOPLE_TOAST: Record<PeopleEdit, string> = {
  same: "Merged; the graph is rebuilt",
  different: "Kept apart; the graph is rebuilt",
  hide: "Hidden; the graph is rebuilt",
};

/** Put text on the clipboard. Falls back to a hidden textarea where the async API isn't allowed. */
async function copyText(text: string): Promise<boolean> {
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

/** The status each action that changes a draft's file leaves it in. */
const STATUS_AFTER = { approve: "approved", discard: "discarded", sent: "sent" } as const;

/** Go to a link the way a person clicking it would: a web page in a new tab, an app's address in place. */
function launch(url: string) {
  if (/^https?:/i.test(url)) window.open(url, "_blank", "noopener,noreferrer");
  else window.location.href = url;
}

/** Save text as a file through the browser's own download. */
function download(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/**
 * The drafts and what to do with one. Approve, discard and sent change the draft's status in
 * its file, edit saves a new body, copy and open only log. Open puts the draft into the app it's
 * for (Gmail, WhatsApp, Slack, LinkedIn, a download) and stops there: the reader presses send,
 * then tells Proxenos with `sent`. `onChange` runs after a write lands, to refresh counts elsewhere.
 */
export function useDrafts(onChange?: () => void) {
  const { data, error, setData, setError } = useJson<DraftsViewResponse>("/api/drafts");
  const notify = useToast();
  const { flashId, flash } = useFlash();

  const patch = useCallback(
    (id: string, change: Partial<Draft>) =>
      setData((d) => (d ? { ...d, drafts: d.drafts.map((x) => (x.id === id ? { ...x, ...change } : x)) } : d)),
    [setData],
  );

  /** The review record that came back with a saved action. */
  const take = useCallback(
    (record: DraftReviews | null) => {
      if (record) setData((d) => (d ? { ...d, record } : d));
    },
    [setData],
  );

  const resync = useCallback(
    () =>
      getJson<DraftsViewResponse>("/api/drafts").then(
        (d) => setData(d),
        () => {
          // The error banner already says the write failed.
        },
      ),
    [setData],
  );

  const setStatus = useCallback(
    (draft: Draft, action: keyof typeof STATUS_AFTER) => {
      const status = STATUS_AFTER[action];
      if (draft.status === status) return;
      flash(draft.id);
      patch(draft.id, { status });
      sendDraftAction(draft.id, action).then(
        (record) => {
          take(record);
          notify(DRAFT_TOAST[action], action === "discard" ? "info" : "ok");
          onChange?.();
        },
        () => {
          patch(draft.id, { status: draft.status });
          setError(SAVE_FAILED);
          resync();
        },
      );
    },
    [patch, take, flash, notify, onChange, setError, resync],
  );

  /** Resolves true once the new body is saved in the file. */
  const edit = useCallback(
    async (draft: Draft, body: string): Promise<boolean> => {
      try {
        take(await sendDraftAction(draft.id, "edit", body));
      } catch {
        setError(SAVE_FAILED);
        return false;
      }
      patch(draft.id, { body: body.trim() });
      flash(draft.id);
      notify(DRAFT_TOAST.edit, "ok");
      return true;
    },
    [patch, take, flash, notify, setError],
  );

  const copy = useCallback(
    async (draft: Draft) => {
      if (!(await copyText(draft.body))) {
        setError("Couldn't reach the clipboard. Select the text and copy it by hand.");
        return;
      }
      notify(DRAFT_TOAST.copy, "ok");
      sendDraftAction(draft.id, "copy").catch(() => {
        // The text is copied; only the log line is lost.
      });
    },
    [notify, setError],
  );

  /**
   * Open the draft in its app, or its second way in (the mail app) when `viaAlt`. The copy and
   * the opening both start inside the click, so the browser still counts them as the reader's
   * own. Resolves true once it has gone to the app, for the "Sent?" question that follows.
   */
  const open = useCallback(
    async (draft: Draft, viaAlt = false): Promise<boolean> => {
      const plan = data?.actions[draft.id];
      const step = viaAlt ? plan?.alt : plan;
      if (!plan || !step) return false;
      const copied = step.copy ? copyText(openText(draft)) : null;
      if (plan.target === "file") {
        const file = markdownFile(draft);
        download(file.filename, file.text);
      } else if (step.url) launch(step.url);
      sendDraftAction(draft.id, "opened").catch(() => {
        // Only the log line is lost.
      });
      if (copied && !(await copied)) {
        setError("Couldn't reach the clipboard. Select the text and copy it by hand.");
      } else notify(step.note, "ok");
      return true;
    },
    [data, notify, setError],
  );

  return {
    data,
    error,
    flashId,
    approve: (d: Draft) => setStatus(d, "approve"),
    discard: (d: Draft) => setStatus(d, "discard"),
    sent: (d: Draft) => setStatus(d, "sent"),
    edit,
    copy,
    open,
    clearError: () => setError(null),
  };
}

// ── Last visit ──────────────────────────────────────────────────────────────

const VISIT_KEY = "proxenos.visit";
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
