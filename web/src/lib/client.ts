"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { Action, FeedItem, ItemsResponse, Reaction } from "./types";

export const POLL_MS = 5 * 60 * 1000;

export async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`${url} returned ${res.status}`);
  return (await res.json()) as T;
}

export async function sendFeedback(itemId: string, action: Action): Promise<void> {
  const res = await fetch("/api/feedback", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ item_id: itemId, action }),
    keepalive: true,
  });
  if (!res.ok) throw new Error(`feedback returned ${res.status}`);
}

export function withReaction(items: FeedItem[], id: string, reaction: Reaction | null): FeedItem[] {
  return items.map((it) => (it.id === id ? { ...it, reaction } : it));
}

export function withOpened(items: FeedItem[], id: string): FeedItem[] {
  return items.map((it) => (it.id === id ? { ...it, opened: true } : it));
}

/** Fetch JSON once per mount. */
export function useJson<T>(url: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    getJson<T>(url).then(
      (d) => alive && setData(d),
      (e: unknown) => alive && setError(String(e)),
    );
    return () => {
      alive = false;
    };
  }, [url]);
  return { data, error, setData };
}

type Patch = (items: FeedItem[]) => FeedItem[];

/**
 * Items and card actions shared by the Feed and Saved views. With `poll`, it
 * re-checks every five minutes and holds a newer batch in `pending` until
 * the reader asks for it, so cards don't move under the cursor.
 */
export function useItems(url: string, poll = false) {
  const [data, setData] = useState<ItemsResponse | null>(null);
  const [pending, setPending] = useState<ItemsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Batch currently on screen; undefined until the first load.
  const shownBatch = useRef<string | null | undefined>(undefined);

  const accept = useCallback((next: ItemsResponse) => {
    shownBatch.current = next.latest?.batch ?? null;
    setData(next);
    setPending(null);
  }, []);

  const load = useCallback(
    (force: boolean) =>
      getJson<ItemsResponse>(url).then(
        (next) => {
          setError(null);
          const shown = shownBatch.current;
          if (force || !shown || !next.latest || next.latest.batch === shown) accept(next);
          else setPending(next);
        },
        (e: unknown) => setError(String(e)),
      ),
    [url, accept],
  );

  useEffect(() => {
    load(true);
    if (!poll) return;
    const timer = setInterval(() => load(false), POLL_MS);
    return () => clearInterval(timer);
  }, [load, poll]);

  const patch = useCallback((fn: Patch) => {
    setData((d) => (d ? { ...d, items: fn(d.items) } : d));
    setPending((p) => (p ? { ...p, items: fn(p.items) } : p));
  }, []);

  const react = useCallback(
    (item: FeedItem, reaction: Reaction) => {
      if (item.reaction === reaction) return;
      patch((items) => withReaction(items, item.id, reaction));
      sendFeedback(item.id, reaction).catch(() => {
        patch((items) => withReaction(items, item.id, item.reaction));
        setError("Couldn't save that reaction. Is the vault reachable?");
      });
    },
    [patch],
  );

  const open = useCallback(
    (item: FeedItem) => {
      patch((items) => withOpened(items, item.id));
      sendFeedback(item.id, "open").catch(() => {
        // Opening still works; only the log line is lost.
      });
    },
    [patch],
  );

  const showPending = useCallback(() => {
    if (pending) accept(pending);
  }, [pending, accept]);

  return {
    data,
    pending,
    error,
    refresh: () => load(true),
    check: () => load(false),
    showPending,
    react,
    open,
  };
}
