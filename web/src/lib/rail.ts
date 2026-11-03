"use client";

// Whether the sidebar shows labels or only icons, per device. The reader's pick is kept in
// localStorage and set on <html> as data-rail, which globals.css's rail-icons variant draws from;
// with no pick, a window under 1100px gets icons only. CSS draws it, so it's right from the first
// frame; this only says which it is, for the button that switches it.

import { useSyncExternalStore } from "react";

import { RAIL_KEY, RAIL_NARROW } from "./railScript";

const listeners = new Set<() => void>();

function collapsed(): boolean {
  const picked = document.documentElement.getAttribute("data-rail");
  return picked ? picked === "collapsed" : window.matchMedia(RAIL_NARROW).matches;
}

function subscribe(listener: () => void) {
  const narrow = window.matchMedia(RAIL_NARROW);
  narrow.addEventListener("change", listener);
  listeners.add(listener);
  return () => {
    narrow.removeEventListener("change", listener);
    listeners.delete(listener);
  };
}

/** Icons only, or labels, on this device from now on. */
export function setRailCollapsed(value: boolean) {
  const picked = value ? "collapsed" : "expanded";
  document.documentElement.setAttribute("data-rail", picked);
  try {
    localStorage.setItem(RAIL_KEY, picked);
  } catch {
    // Blocked storage: the pick holds until the page is reloaded.
  }
  listeners.forEach((l) => l());
}

/** Whether the sidebar is icons only, kept current. Labels until the page is on the client. */
export function useRailCollapsed(): boolean {
  return useSyncExternalStore(subscribe, collapsed, () => false);
}
