"use client";

// The Connect view's data and actions: every source's status, and the sign-ins, reads and token
// saves the page starts. While one runs, its state is checked every couple of seconds; when it ends, the
// sources are read again so the card shows what changed.

import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "@/components/Toasts";

import { getJson } from "./client";
import type { ConnectJob, ConnectJobKind, ConnectJobsResponse, ConnectResponse, SignInKind } from "./types";
import { SIGN_IN_KINDS } from "./types";

const POLL_MS = 2000;

/** The toast for a job that worked. Failures stay on their card instead. */
function doneToast(job: ConnectJob): string {
  if ((SIGN_IN_KINDS as readonly string[]).includes(job.kind)) return `Signed in as ${job.account ?? "that account"}`;
  return job.kind === "beeper" ? "Beeper token saved" : "WhatsApp read";
}

/** POST a JSON body. Resolves with the parsed answer, or throws the server's error text. */
async function post<T>(url: string, body: object): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const answer = (await res.json().catch(() => ({}))) as T & { error?: string };
  if (!res.ok) throw new Error(answer.error ?? `${url} returned ${res.status}`);
  return answer;
}

export function useConnect() {
  const [data, setData] = useState<ConnectResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const notify = useToast();
  // The jobs as last seen, to tell when one has just ended.
  const seen = useRef<ConnectJob[]>([]);

  const load = useCallback(() => {
    getJson<ConnectResponse>("/api/connect").then(
      (d) => {
        seen.current = d.jobs;
        setData(d);
        setError(null);
      },
      (e: unknown) => setError(String(e)),
    );
  }, []);

  useEffect(load, [load]);

  const running = data?.jobs.some((j) => j.state === "running") ?? false;
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      getJson<ConnectJobsResponse>("/api/connect/jobs").then(
        (r) => {
          const ended = r.jobs.filter((j) => j.state !== "running" && seen.current.some((s) => s.kind === j.kind && s.state === "running"));
          seen.current = r.jobs;
          setData((d) => (d ? { ...d, now: r.now, jobs: r.jobs } : d));
          for (const j of ended) if (j.state === "done") notify(doneToast(j), "ok");
          if (ended.length) load();
        },
        () => {
          // A missed check is retried on the next tick.
        },
      );
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [running, load, notify]);

  const started = useCallback((job: ConnectJob) => {
    seen.current = [...seen.current.filter((j) => j.kind !== job.kind), job];
    setData((d) => (d ? { ...d, jobs: [...d.jobs.filter((j) => j.kind !== job.kind), job] } : d));
  }, []);

  /** Start a Gmail, Microsoft 365 or Google Calendar sign-in for this account. Resolves with why it couldn't start, or null. */
  const signIn = useCallback(
    (kind: SignInKind, name: string, address: string): Promise<string | null> =>
      post<{ job: ConnectJob }>(`/api/connect/${kind}`, { name, address }).then(
        (r) => {
          started(r.job);
          return null;
        },
        (e: unknown) => (e instanceof Error ? e.message : String(e)),
      ),
    [started],
  );

  /**
   * Hand Beeper's token to the server, which passes it to `proxenos auth beeper` on stdin. Resolves
   * with why it couldn't start, or null. The token is in this request and nowhere else.
   */
  const saveBeeperToken = useCallback(
    (token: string): Promise<string | null> =>
      post<{ job: ConnectJob }>("/api/connect/beeper", { token }).then(
        (r) => {
          started(r.job);
          return null;
        },
        (e: unknown) => (e instanceof Error ? e.message : String(e)),
      ),
    [started],
  );

  const readWhatsApp = useCallback(() => {
    post<{ job: ConnectJob }>("/api/connect/whatsapp", {}).then(
      (r) => started(r.job),
      (e: unknown) => setError(e instanceof Error ? e.message : String(e)),
    );
  }, [started]);

  const cancel = useCallback((kind: ConnectJobKind) => {
    post("/api/connect/cancel", { kind }).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const job = useCallback((kind: ConnectJobKind) => data?.jobs.find((j) => j.kind === kind) ?? null, [data]);

  return { data, error, clearError: () => setError(null), job, signIn, readWhatsApp, saveBeeperToken, cancel };
}
