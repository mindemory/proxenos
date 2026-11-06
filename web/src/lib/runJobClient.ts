"use client";

// A background command the page starts and follows by its last line: a model's download
// (/api/setup/pull) and an empty view being made (/api/make). While one runs, its state is read
// every second and a half; when it ends, `onEnd` is told how, once. A job that had ended before
// the page was opened isn't reported again.

import { useCallback, useEffect, useRef, useState } from "react";

import { getJson } from "./client";
import { JSON_HEADERS, PAGE_HEADER } from "./headers";
import type { RunJob, RunJobResponse } from "./types";

const POLL_MS = 1500;

export function useRunJob(url: string, onEnd?: (job: RunJob) => void) {
  const [job, setJob] = useState<RunJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wasRunning = useRef(false);
  const ended = useRef(onEnd);
  useEffect(() => {
    ended.current = onEnd;
  });

  const take = useCallback((next: RunJob | null) => {
    if (wasRunning.current && next && next.state !== "running") ended.current?.(next);
    wasRunning.current = next?.state === "running";
    setJob(next);
  }, []);

  const load = useCallback(() => {
    getJson<RunJobResponse>(url).then(
      (d) => take(d.job),
      () => {}, // the next look tries again
    );
  }, [url, take]);

  useEffect(load, [load]);

  const running = job?.state === "running";
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(timer);
  }, [running, load]);

  /** Start the command with this body. Resolves once it's running; the error is kept in `error`. */
  const start = useCallback(
    async (body: object) => {
      setError(null);
      try {
        const res = await fetch(url, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) });
        const answer = (await res.json().catch(() => ({}))) as Partial<RunJobResponse> & { error?: string };
        if (!res.ok || !answer.job) throw new Error(answer.error ?? `${url} returned ${res.status}`);
        take(answer.job);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [url, take],
  );

  const stop = useCallback(() => {
    fetch(url, { method: "DELETE", headers: { [PAGE_HEADER]: "1" } }).then(load, () => {});
  }, [url, load]);

  return { job, error, start, stop };
}
