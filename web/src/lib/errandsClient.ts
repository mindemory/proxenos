"use client";

// The Errands view's data and actions: the newest errands, starting one, and sending or dropping
// what one wrote. An errand takes a minute or more on a local model, so the page checks every few
// seconds while one is being carried out or a Send is going, and picks up one already running when
// the view opens.

import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "@/components/Toasts";

import { getJson } from "./client";
import type { ErrandEdits, ErrandsResponse } from "./types";

const POLL_MS = 4000;

async function post(body: object): Promise<void> {
  let res: Response;
  try {
    res = await fetch("/api/errands", {
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

/** What the page started and is waiting to hear the end of: an errand, or a Send or Drop. */
interface Waiting {
  kind: "errand" | "send";
  /** When it was started, so its own job can be told from an earlier one. */
  since: number;
  label: string;
}

export function useErrands() {
  const [data, setData] = useState<ErrandsResponse | null>(null);
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
    (d: ErrandsResponse) => {
      setData(d);
      const left: Waiting[] = [];
      for (const w of waitingRef.current) {
        const job = w.kind === "errand" ? d.job : d.sending;
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
    getJson<ErrandsResponse>("/api/errands").then(absorb, (e: unknown) => setError(String(e)));
  }, [absorb]);

  useEffect(load, [load]);

  const running =
    data?.job?.state === "running" || data?.sending?.state === "running" || (data?.errands.some((e) => e.status === "working") ?? false);
  const polling = waiting.length > 0 || running;
  useEffect(() => {
    if (!polling) return;
    const check = () => {
      getJson<ErrandsResponse>("/api/errands").then(absorb, () => {
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

  const start = useCallback((goal: string) => act({ goal }, { kind: "errand", label: "The errand is as far as it can go" }), [act]);

  /** Send one message of an errand, with the edits made to it on the page. */
  const send = useCallback(
    (id: string, index: number, edits: ErrandEdits) => act({ send: id, index, ...edits }, { kind: "send", label: "Sent" }),
    [act],
  );

  const drop = useCallback((id: string) => act({ drop: id }, { kind: "send", label: "Dropped" }), [act]);

  return {
    data,
    error,
    clearError: () => setError(null),
    waiting,
    start,
    send,
    drop,
  };
}
