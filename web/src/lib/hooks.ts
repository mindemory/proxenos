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

/**
 * Whether a scrolling element has more above and below what shows, kept current as it scrolls,
 * resizes or its content grows, so it can fade out at those edges (`scroll-fade` in globals.css).
 */
export function useScrollEdges(el: HTMLElement | null): { above: boolean; below: boolean } {
  const [edges, setEdges] = useState({ above: false, below: false });
  useEffect(() => {
    if (!el) return;
    const measure = () => {
      const above = el.scrollTop > 1;
      const below = el.scrollTop + el.clientHeight < el.scrollHeight - 1;
      setEdges((e) => (e.above === above && e.below === below ? e : { above, below }));
    };
    measure();
    const watch = new ResizeObserver(measure);
    watch.observe(el);
    for (const child of el.children) watch.observe(child);
    el.addEventListener("scroll", measure, { passive: true });
    return () => {
      watch.disconnect();
      el.removeEventListener("scroll", measure);
    };
  }, [el]);
  return edges;
}
