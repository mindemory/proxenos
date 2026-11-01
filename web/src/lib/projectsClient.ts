"use client";

// The Projects view's data and actions: each project, where it stands and the steps taken on it;
// taking a step now, queueing one, and accepting or discarding what a step did. A step takes many
// minutes, so the page checks every few seconds while one is being taken or a decision is going,
// and picks up one already running when the view opens. A project's manuscript, its versions and
// their changes, and a step's changes, are read when asked for (useManuscript, useStepChanges); an
// edit to the manuscript is saved like a decision, as a step waiting on the user.

import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "@/components/Toasts";

import { getJson } from "./client";
import type { ManuscriptEdit, ManuscriptResponse, ProjectsResponse, StepAsk, StepChangesResponse } from "./types";

const POLL_MS = 5000;

async function post(body: object, url = "/api/projects"): Promise<void> {
  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error("Couldn't reach Proxenos. Is your Mac awake?");
  }
  if (res.status >= 200 && res.status < 300) return;
  const answer = (await res.json().catch(() => ({}))) as { error?: string };
  throw new Error(answer.error ?? `The server answered ${res.status}.`);
}

/** What the page started and is waiting to hear the end of: a step, or a decision. */
interface Waiting {
  kind: "step" | "decide";
  /** When it was started, so its own job can be told from an earlier one. */
  since: number;
  label: string;
}

export function useProjects() {
  const [data, setData] = useState<ProjectsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [waiting, setWaiting] = useState<Waiting[]>([]);
  const waitingRef = useRef<Waiting[]>([]);
  const notify = useToast();

  const track = useCallback((next: Waiting[]) => {
    waitingRef.current = next;
    setWaiting(next);
  }, []);

  /** Take in what the server says, and tell the user of anything they started that has ended. */
  const absorb = useCallback(
    (d: ProjectsResponse) => {
      setData(d);
      const left: Waiting[] = [];
      for (const w of waitingRef.current) {
        const job = w.kind === "step" ? d.job : d.deciding;
        const mine = job && Date.parse(job.started) >= w.since - 2000;
        if (!mine || job.state === "running") {
          left.push(w);
          continue;
        }
        if (job.state === "done") notify(w.label, "ok");
        else setError(job.message || "It stopped before it finished.");
      }
      if (left.length !== waitingRef.current.length) track(left);
    },
    [notify, track],
  );

  const load = useCallback(() => {
    getJson<ProjectsResponse>("/api/projects").then(absorb, (e: unknown) => setError(String(e)));
  }, [absorb]);

  useEffect(load, [load]);

  const running =
    data?.job?.state === "running" ||
    data?.deciding?.state === "running" ||
    (data?.projects.some((p) => p.steps.some((s) => s.status === "working")) ?? false);
  const polling = waiting.length > 0 || running;
  useEffect(() => {
    if (!polling) return;
    const check = () => {
      getJson<ProjectsResponse>("/api/projects").then(absorb, () => {
        // A missed check is made again on the next tick.
      });
    };
    const timer = window.setInterval(check, POLL_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") check();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [polling, absorb]);

  const act = useCallback(
    async (body: object, w: Omit<Waiting, "since">, url?: string): Promise<boolean> => {
      const since = Date.now();
      try {
        await post(body, url);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        return false;
      }
      setError(null);
      track([...waitingRef.current, { ...w, since }]);
      load();
      return true;
    },
    [load, track],
  );

  const take = useCallback(
    (project: string) => act({ take: project }, { kind: "step", label: "The step is done: it's waiting on you" }),
    [act],
  );
  const accept = useCallback((step: string) => act({ accept: step }, { kind: "decide", label: "Accepted and merged" }), [act]);
  const discard = useCallback((step: string) => act({ discard: step }, { kind: "decide", label: "Discarded" }), [act]);
  const queue = useCallback(
    (project: string, step: string, ask?: StepAsk) => act({ queue: project, step, ...ask }, { kind: "decide", label: "Queued" }),
    [act],
  );
  /** Ask for a step and take it now, ahead of the queue. */
  const takeAsked = useCallback(
    (project: string, step: string, ask?: StepAsk) =>
      act({ take: project, step, ...ask }, { kind: "step", label: "The step is done: it's waiting on you" }),
    [act],
  );
  const unqueue = useCallback(
    (project: string, id: string) => act({ unqueue: project, id }, { kind: "decide", label: "Taken off the queue" }),
    [act],
  );
  /** Save the user's own text for the manuscript, as a step waiting on them. */
  const saveEdit = useCallback(
    (project: string, edit: ManuscriptEdit) =>
      act({ edit: project, ...edit }, { kind: "decide", label: "Saved on a branch of its own: it's waiting on you" }, "/api/projects/manuscript"),
    [act],
  );

  return {
    data,
    error,
    clearError: () => setError(null),
    waiting,
    take,
    takeAsked,
    accept,
    discard,
    queue,
    unqueue,
    saveEdit,
  };
}

/** GET a JSON answer, or throw what the server said was wrong. */
async function read<T>(url: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, { cache: "no-store" });
  } catch {
    throw new Error("Couldn't reach Proxenos. Is your Mac awake?");
  }
  const answer = (await res.json().catch(() => ({}))) as T & { error?: string };
  if (!res.ok) throw new Error(answer.error ?? `The server answered ${res.status}.`);
  return answer;
}

/** A read made when `url` is set and again whenever it or `again` changes; the last answer stays while the next loads. */
function useRead<T>(url: string | null, again: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  // What the last answer was for: until it's this read's, this read is loading.
  const [answered, setAnswered] = useState("");
  const key = `${url} ${again}`;
  useEffect(() => {
    if (!url) return;
    let live = true;
    read<T>(url).then(
      (d) => {
        if (!live) return;
        setData(d);
        setError(null);
        setAnswered(key);
      },
      (e: unknown) => {
        if (!live) return;
        setError(e instanceof Error ? e.message : String(e));
        setAnswered(key);
      },
    );
    return () => {
      live = false;
    };
  }, [url, key]);
  return { data, error, loading: url !== null && answered !== key };
}

/**
 * The project's manuscript while `open`: one version (`head`, by default the newest) with its
 * changes since another (`base`, by default the one before), read again when `again` changes (a
 * step or an edit came or went).
 */
export function useManuscript(project: string, open: boolean, base: string, head: string, again: string) {
  const query = new URLSearchParams({ project });
  if (base) query.set("base", base);
  if (head) query.set("head", head);
  return useRead<ManuscriptResponse>(open ? `/api/projects/manuscript?${query}` : null, again);
}

/** Every file a step changed, while `open`. */
export function useStepChanges(project: string, step: string, open: boolean) {
  const query = new URLSearchParams({ project, step });
  return useRead<StepChangesResponse>(open ? `/api/projects/manuscript?${query}` : null, "");
}
