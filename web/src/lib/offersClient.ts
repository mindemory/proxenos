"use client";

// The Offers view's data and its one action: starting a comparison. A comparison reads each offer
// and writes a reply to each, minutes on a local model, so the page checks every few seconds while
// one is being made, and picks up one already running when the view opens.

import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "@/components/Toasts";

import { getJson } from "./client";
import type { OffersRequest, OffersResponse } from "./types";
import { JSON_HEADERS } from "./headers";

const POLL_MS = 4000;

export function useOffers() {
  const [data, setData] = useState<OffersResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  // When the page started a comparison it's waiting to hear the end of, so its own job can be told from an earlier one.
  const [since, setSince] = useState<number | null>(null);
  const sinceRef = useRef<number | null>(null);
  const notify = useToast();

  const wait = useCallback((at: number | null) => {
    sinceRef.current = at;
    setSince(at);
  }, []);

  /** Take in what the server says, and tell the user when the comparison they started has ended. */
  const absorb = useCallback(
    (d: OffersResponse) => {
      setData(d);
      const at = sinceRef.current;
      const job = d.job;
      if (at === null || !job || Date.parse(job.started) < at - 2000 || job.state === "running") return;
      if (job.state === "done") notify("The offers are compared", "ok");
      else setError(job.message || "It stopped before it finished.");
      wait(null);
    },
    [notify, wait],
  );

  const load = useCallback(() => {
    getJson<OffersResponse>("/api/offers").then(absorb, (e: unknown) => setError(String(e)));
  }, [absorb]);

  useEffect(load, [load]);

  const running = data?.job?.state === "running" || (data?.comparisons.some((c) => c.status === "working") ?? false);
  const polling = since !== null || running;
  useEffect(() => {
    if (!polling) return;
    const check = () => {
      getJson<OffersResponse>("/api/offers").then(absorb, () => {
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

  /** Start a comparison. Resolves with whether the server took it. */
  const start = useCallback(
    async (request: OffersRequest): Promise<boolean> => {
      const at = Date.now();
      let res: Response;
      try {
        res = await fetch("/api/offers", {
          method: "POST",
          headers: JSON_HEADERS,
          body: JSON.stringify(request),
        });
      } catch {
        setError("Couldn't reach Proxenos. Is your Mac awake?");
        return false;
      }
      if (res.status < 200 || res.status >= 300) {
        const answer = (await res.json().catch(() => ({}))) as { error?: string };
        setError(answer.error ?? `The server answered ${res.status}.`);
        return false;
      }
      setError(null);
      wait(at);
      load();
      return true;
    },
    [load, wait],
  );

  return { data, error, clearError: () => setError(null), waiting: since !== null, start };
}
