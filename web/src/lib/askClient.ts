"use client";

// The Ask view's data and actions: the newest asks, sending a question, and following the one
// being thought through. A local model can take many minutes, so the page checks every few seconds
// for as long as an ask is going, and can be left and come back to: an ask running on the server
// is picked up again when the view opens.

import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "@/components/Toasts";

import { getJson, useFlash } from "./client";
import type { AskImage, AskResponse } from "./types";

const POLL_MS = 5000;

/** An ask this page is waiting on. */
export interface Pending {
  /** When it began, in ms since 1970. */
  since: number;
  question: string;
  images: number;
  /** The asks that were there before it, so its own can be told from them. */
  known: string[];
}

async function postJson<T>(url: string, body: object): Promise<{ status: number; answer: T & { error?: string } }> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return { status: res.status, answer: (await res.json().catch(() => ({}))) as T & { error?: string } };
}

/** `onEnd` is told when the ask being waited on is over: true if it was answered. */
export function useAsk(onEnd: (answered: boolean) => void) {
  const [data, setData] = useState<AskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [stopping, setStopping] = useState(false);
  const { flashId, flash } = useFlash();
  const notify = useToast();
  const pendingRef = useRef<Pending | null>(null);
  const dataRef = useRef<AskResponse | null>(null);
  const onEndRef = useRef(onEnd);
  useEffect(() => {
    onEndRef.current = onEnd;
  });

  const track = useCallback((next: Pending | null) => {
    pendingRef.current = next;
    setPending(next);
    if (!next) setStopping(false);
  }, []);

  /** Take in what the server says, and work out whether the ask being waited on has ended. */
  const absorb = useCallback(
    (d: AskResponse) => {
      dataRef.current = d;
      setData(d);

      let waiting = pendingRef.current;
      if (!waiting && d.job?.state === "running") {
        // One already going, started before this page opened or from another device: follow it.
        const going = d.asks.find((a) => a.status === "working");
        waiting = {
          since: Date.parse(d.job.started) || Date.now(),
          question: going?.question ?? "",
          images: going?.images ?? 0,
          known: d.asks.filter((a) => a.status !== "working").map((a) => a.id),
        };
        track(waiting);
      }
      if (!waiting) return;

      const known = new Set(waiting.known);
      const jobId = d.job?.id;
      // The newest ask that wasn't there before, or the one the command says it finished.
      const mine = jobId ? d.asks.find((a) => a.id === jobId) : d.asks.find((a) => !known.has(a.id));
      if (mine && mine.status !== "working") {
        track(null);
        setError(null);
        flash(mine.id);
        if (mine.status === "done") notify("Your answer is ready", "ok");
        onEndRef.current(mine.status === "done");
        return;
      }
      if (d.job?.state !== "running") {
        // The command is over and left no answer behind.
        track(null);
        if (d.job?.state === "failed") setError(d.job.message || "It stopped before it finished.");
        else if (d.job?.state !== "stopped") setError("It stopped before it finished.");
        onEndRef.current(false);
      }
    },
    [track, flash, notify],
  );

  const load = useCallback(() => {
    getJson<AskResponse>("/api/ask").then(absorb, (e: unknown) => {
      if (!dataRef.current) setError(String(e));
    });
  }, [absorb]);

  useEffect(load, [load]);

  const polling = pending !== null || (data?.asks.some((a) => a.status === "working") ?? false);
  useEffect(() => {
    if (!polling) return;
    const check = () => {
      getJson<AskResponse>("/api/ask").then(absorb, () => {
        // A missed check is made again on the next tick.
      });
    };
    const timer = window.setInterval(check, POLL_MS);
    // A phone that was asleep checks as soon as it's looked at again, not up to five seconds later.
    const onVisible = () => {
      if (document.visibilityState === "visible") check();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [polling, absorb]);

  /** Send a question. Resolves true once the server has taken it. */
  const send = useCallback(
    async (text: string, images: AskImage[]): Promise<boolean> => {
      try {
        const { status, answer } = await postJson<object>("/api/ask", { text, images });
        if (status === 409) {
          // Another is running (from another tab or device): follow that one.
          load();
          throw new Error(answer.error ?? "Another question is still being thought through.");
        }
        if (status < 200 || status >= 300) throw new Error(answer.error ?? `The server answered ${status}.`);
        setError(null);
        track({
          since: Date.now(),
          question: text,
          images: images.length,
          known: (dataRef.current?.asks ?? []).map((a) => a.id),
        });
        return true;
      } catch (e) {
        setError(e instanceof TypeError ? "Couldn't reach Proxenos. Is your Mac awake?" : e instanceof Error ? e.message : String(e));
        return false;
      }
    },
    [load, track],
  );

  /** Stop the ask that's running. */
  const stop = useCallback(() => {
    setStopping(true);
    postJson<{ stopped?: boolean }>("/api/ask/cancel", {}).then(
      () => load(),
      () => setStopping(false),
    );
  }, [load]);

  return { data, error, clearError: () => setError(null), pending, stopping, flashId, send, stop };
}
