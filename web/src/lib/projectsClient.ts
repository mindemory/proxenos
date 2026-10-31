"use client";

// The Projects view's data and actions: each project, where it stands and the steps taken on it;
// taking a step now, queueing one, and accepting or discarding what a step did. A step takes many
// minutes, so the page checks every few seconds while one is being taken or a decision is going,
// and picks up one already running when the view opens.

import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "@/components/Toasts";

import { getJson } from "./client";
import type { ProjectsResponse } from "./types";

const POLL_MS = 5000;

async function post(body: object): Promise<void> {
  let res: Response;
  try {
    res = await fetch("/api/projects", {
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
    async (body: object, w: Omit<Waiting, "since">): Promise<boolean> => {
      const since = Date.now();
      try {
        await post(body);
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
    (project: string, step: string) => act({ queue: project, step }, { kind: "decide", label: "Queued" }),
    [act],
  );
  const unqueue = useCallback(
    (project: string, id: string) => act({ unqueue: project, id }, { kind: "decide", label: "Taken off the queue" }),
    [act],
  );

  return {
    data,
    error,
    clearError: () => setError(null),
    waiting,
    take,
    accept,
    discard,
    queue,
    unqueue,
  };
}
