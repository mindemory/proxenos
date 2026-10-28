"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

/** Whether a media query matches, kept current. False until the page is on the client. */
export function useMedia(query: string): boolean {
  return useSyncExternalStore(
    (notify) => {
      const m = window.matchMedia(query);
      m.addEventListener("change", notify);
      return () => m.removeEventListener("change", notify);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

/** An element's size in CSS pixels, kept current. Attach the first value as its ref. */
export function useBox<T extends HTMLElement>(): [(el: T | null) => void, { w: number; h: number }] {
  const [el, setEl] = useState<T | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    if (!el) return;
    const watch = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize((s) => (s.w === width && s.h === height ? s : { w: width, h: height }));
    });
    watch.observe(el);
    return () => watch.disconnect();
  }, [el]);
  return [setEl, size];
}
