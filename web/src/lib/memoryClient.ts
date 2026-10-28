"use client";

import { useEffect, useState } from "react";

import type { MemoryContextResponse, MemorySearchResponse } from "./types";

export interface MemoryQuery {
  q: string;
  sources: string[];
  who: string;
  since: string;
  until: string;
  limit?: number;
}

export function searchUrl(p: MemoryQuery): string {
  const params = new URLSearchParams();
  if (p.q) params.set("q", p.q);
  if (p.sources.length) params.set("source", p.sources.join(","));
  if (p.who) params.set("who", p.who);
  if (p.since) params.set("since", p.since);
  if (p.until) params.set("until", p.until);
  if (p.limit) params.set("limit", String(p.limit));
  return `/api/memory/search?${params}`;
}

/** The latest of a series of requests: an answer to an older one never replaces a newer one. */
function useLatest<T>(url: string | null) {
  const [state, setState] = useState<{ url: string; data: T | null; error: string | null } | null>(null);
  useEffect(() => {
    if (!url) return;
    const ctrl = new AbortController();
    fetch(url, { cache: "no-store", signal: ctrl.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(res.status === 404 ? "not found" : `returned ${res.status}`);
        return (await res.json()) as T;
      })
      .then(
        (data) => setState({ url, data, error: null }),
        (e: unknown) => {
          if (ctrl.signal.aborted) return;
          setState((prev) => ({ url, data: prev?.data ?? null, error: e instanceof Error ? e.message : String(e) }));
        },
      );
    return () => ctrl.abort();
  }, [url]);
  return {
    data: state?.data ?? null,
    error: state && state.url === url ? state.error : null,
    /** An answer for this very request hasn't arrived yet; `data` is then the previous one. */
    loading: url !== null && state?.url !== url,
  };
}

/** Search results for a query, keeping the previous ones on screen while the next load. */
export function useMemorySearch(p: MemoryQuery) {
  return useLatest<MemorySearchResponse>(searchUrl(p));
}

/** The conversation around one record. */
export function useMemoryContext(id: string | null) {
  const { data, error, loading } = useLatest<MemoryContextResponse>(
    id ? `/api/memory/context?id=${encodeURIComponent(id)}` : null,
  );
  return { data: data && data.id === id ? data : null, error, loading };
}

/** A value that follows `value` after it has held still for `ms`. */
export function useDebounced<T>(value: T, ms: number): T {
  const [later, setLater] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setLater(value), ms);
    return () => window.clearTimeout(timer);
  }, [value, ms]);
  return later;
}
