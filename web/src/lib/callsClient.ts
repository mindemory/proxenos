"use client";

// The Calls view's data and actions: the sheets, starting a call and hanging up. A call can sit on
// hold for an hour, so while one is going the page checks every few seconds; otherwise it reads
// once and again after each action.

import { useCallback, useEffect, useState } from "react";

import { useToast } from "@/components/Toasts";

import { getJson } from "./client";
import type { CallsResponse } from "./types";
import { JSON_HEADERS } from "./headers";

const POLL_MS = 3000;

async function post(url: string, body: { id: string; anyway?: boolean }): Promise<string> {
  let res: Response;
  try {
    res = await fetch(url, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) });
  } catch {
    throw new Error("Couldn't reach Proxenos. Is your Mac awake?");
  }
  const answer = (await res.json().catch(() => ({}))) as { message?: string; error?: string };
  if (res.ok) return answer.message ?? "";
  throw new Error(answer.error ?? `The server answered ${res.status}.`);
}

export function useCalls() {
  const [data, setData] = useState<CallsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** The sheet a Call or Hang up was just pressed on, until the server answers. */
  const [busy, setBusy] = useState<string | null>(null);
  const notify = useToast();

  const load = useCallback(
    () =>
      getJson<CallsResponse>("/api/calls").then(
        (d) => {
          setData(d);
          return d;
        },
        (e: unknown) => {
          setError(String(e));
          return null;
        },
      ),
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const going = !!data?.sheets.some((s) => s.live);
  useEffect(() => {
    if (!going) return;
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [going, load]);

  const act = useCallback(
    async (url: string, id: string, anyway?: boolean) => {
      setBusy(id);
      setError(null);
      try {
        notify((await post(url, anyway ? { id, anyway } : { id })) || "Done", "ok");
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(null);
        void load();
      }
    },
    [load, notify],
  );

  return {
    data,
    error,
    busy,
    /** Call the sheet's number; `anyway` calls one the vault doubts, once the reader has seen why. */
    start: (id: string, anyway?: boolean) => act("/api/calls/start", id, anyway),
    stop: (id: string) => act("/api/calls/stop", id),
    clearError: () => setError(null),
  };
}
