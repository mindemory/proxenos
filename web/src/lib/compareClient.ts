"use client";

// Settings' "Which writes like you?": a round comparing two models, picking between their drafts
// blind, and starting another. A round takes minutes with a local model, so while one is being
// drafted the card checks every few seconds, as Errands does, and shows each reply once both its
// drafts are there; one already being drafted when the card opens is followed the same way.

import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "@/components/Toasts";

import { getJson } from "./client";
import type { CompareJob, ComparePick, CompareResponse } from "./types";

const POLL_MS = 5000;

async function post(body: object): Promise<Record<string, unknown>> {
  let res: Response;
  try {
    res = await fetch("/api/compare", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error("Couldn't reach Proxenos. Is your computer awake?");
  }
  const answer = (await res.json().catch(() => ({}))) as Record<string, unknown>;
  if (!res.ok) throw new Error(typeof answer.error === "string" ? answer.error : `The server answered ${res.status}.`);
  return answer;
}

/** `round`: the round to show, or null for the newest. */
export function useCompare() {
  const [round, setRound] = useState<string | null>(null);
  const [data, setData] = useState<CompareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  // When this page started a round, so its own job can be told from an earlier one: in state to
  // keep checking while it runs, and in a ref for the checks themselves.
  const [since, setSince] = useState<number | null>(null);
  const sinceRef = useRef<number | null>(null);
  const notify = useToast();
  const url = round ? `/api/compare?round=${encodeURIComponent(round)}` : "/api/compare";

  const track = useCallback((next: number | null) => {
    sinceRef.current = next;
    setSince(next);
  }, []);

  const absorb = useCallback(
    (d: CompareResponse) => {
      setData(d);
      if (d.error) setError(d.error);
      const s = sinceRef.current;
      const job: CompareJob | null = d.job;
      if (s === null || !job || Date.parse(job.started) < s - 2000 || job.state === "running") return;
      track(null);
      if (job.state === "done") notify("Both models have drafted every reply", "ok");
      else if (job.state === "failed") setError(job.message || "It stopped before it finished.");
    },
    [notify, track],
  );

  const load = useCallback(() => {
    getJson<CompareResponse>(url).then(absorb, (e: unknown) => setError(String(e)));
  }, [url, absorb]);

  useEffect(load, [load]);

  const drafting = since !== null || data?.job?.state === "running" || data?.round?.status === "drafting";
  useEffect(() => {
    if (!drafting) return;
    const check = () => {
      getJson<CompareResponse>(url).then(absorb, () => {
        // A missed check is made again on the next tick.
      });
    };
    const timer = window.setInterval(check, POLL_MS);
    return () => window.clearInterval(timer);
  }, [drafting, url, absorb]);

  /** Draft a new round: `model` against the drafting model set up. Whether it started. */
  const start = useCallback(
    async (model: string, n: number): Promise<boolean> => {
      const at = Date.now();
      try {
        await post({ model, n });
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        return false;
      }
      setError(null);
      track(at);
      setRound(null); // the newest, which this one will be
      getJson<CompareResponse>("/api/compare").then(absorb, () => undefined);
      return true;
    },
    [absorb, track],
  );

  /** Pick for one reply; a new pick replaces the last. */
  const pick = useCallback(
    async (roundId: string, item: number, choice: ComparePick): Promise<boolean> => {
      try {
        const answer = (await post({ round: roundId, item, pick: choice })) as unknown as CompareResponse;
        setError(null);
        absorb(answer);
        return true;
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        return false;
      }
    },
    [absorb],
  );

  const stop = useCallback(async () => {
    try {
      await post({ stop: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    load();
  }, [load]);

  return {
    data,
    error,
    clearError: () => setError(null),
    round,
    show: setRound,
    start,
    pick,
    stop,
    /** This page started a round and hasn't heard it end. */
    starting: since !== null,
  };
}
