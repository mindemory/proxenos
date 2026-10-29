"use client";

// The setup page's and Settings' data and changes. Each change answers with the new status, so
// the page shows what was saved without asking again.

import { useCallback, useEffect, useState } from "react";

import { getJson } from "./client";
import type { SetupChange, SetupResponse, SetupResult, SetupStatus } from "./types";

/** Paths under these, relative to the home folder, are synced to a cloud on most Macs. */
const SYNCED: readonly [string, "icloud" | "drive"][] = [
  ["Desktop", "icloud"],
  ["Documents", "icloud"],
  ["Library/Mobile Documents", "icloud"],
  ["Library/CloudStorage", "drive"],
];

/** Which cloud a typed folder syncs to, if any, by where it sits under `home`. Python checks the same when it's saved. */
export function cloudFor(typed: string, home: string): "icloud" | "drive" | null {
  const p = typed.trim().replace(/\/+$/, "");
  let rel: string | null = null;
  if (p.startsWith("~/")) rel = p.slice(2);
  else if (home && p.startsWith(home + "/")) rel = p.slice(home.length + 1);
  if (rel === null) return null;
  return SYNCED.find(([dir]) => rel === dir || rel.startsWith(dir + "/"))?.[1] ?? null;
}

export function useSetup() {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    getJson<SetupResponse>("/api/setup").then(
      (r) => {
        if (r.status) setStatus(r.status);
        setError(r.error);
      },
      (e: unknown) => setError(String(e)),
    );
  }, []);

  useEffect(load, [load]);

  /** Make one change. Resolves with what was done; rejects with why not, in the page's words. */
  const apply = useCallback(async (change: SetupChange): Promise<string> => {
    const res = await fetch("/api/setup", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(change),
    });
    const answer = (await res.json().catch(() => ({}))) as Partial<SetupResult>;
    if (answer.status) setStatus(answer.status);
    if (!res.ok || !answer.ok) throw new Error(answer.error ?? `The change wasn't saved (${res.status}).`);
    return answer.message ?? "Saved.";
  }, []);

  return { status, error, reload: load, apply };
}
