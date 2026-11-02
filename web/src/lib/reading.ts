"use client";

// How the page reads on this device: text size, typeface, spacing, theme, contrast, motion, and
// how it reads aloud. Kept in localStorage, so each device keeps its own, and applied as
// attributes on <html> that globals.css turns into its variables, so every view follows. The
// defaults set no attribute at all, which leaves the page exactly as designed.

import { useSyncExternalStore } from "react";

import { DEVICE_CALM, DEVICE_CONTRAST, DEVICE_LIGHT, READING_KEY } from "./readingScript";

export type TextSize = "default" | "large" | "larger";
export type Face = "default" | "hyperlegible";
export type Spacing = "normal" | "relaxed";
export type Theme = "dark" | "light" | "system";

export interface Reading {
  size: TextSize;
  face: Face;
  spacing: Spacing;
  theme: Theme;
  /** More contrast. On by itself too when the device asks for it (prefers-contrast: more). */
  contrast: boolean;
  /** Less motion. On by itself too when the device asks for it (prefers-reduced-motion). */
  calm: boolean;
  /** How fast Listen reads, 1 being the voice's own pace. */
  rate: number;
  /** The voice Listen reads with, by its voiceURI, or null for the system's. */
  voice: string | null;
}

export const DEFAULT_READING: Reading = {
  size: "default",
  face: "default",
  spacing: "normal",
  theme: "dark",
  contrast: false,
  calm: false,
  rate: 1,
  voice: null,
};

export const RATE_MIN = 0.6;
export const RATE_MAX = 1.4;

const SIZES: readonly TextSize[] = ["default", "large", "larger"];
const FACES: readonly Face[] = ["default", "hyperlegible"];
const SPACINGS: readonly Spacing[] = ["normal", "relaxed"];
const THEMES: readonly Theme[] = ["dark", "light", "system"];

function pick<T extends string>(v: unknown, allowed: readonly T[], fallback: T): T {
  return allowed.includes(v as T) ? (v as T) : fallback;
}

/** A stored value checked field by field: anything unknown or hand-edited falls back to the default. */
export function parseReading(raw: unknown): Reading {
  const r = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const rate = typeof r.rate === "number" && Number.isFinite(r.rate) ? r.rate : DEFAULT_READING.rate;
  return {
    size: pick(r.size, SIZES, DEFAULT_READING.size),
    face: pick(r.face, FACES, DEFAULT_READING.face),
    spacing: pick(r.spacing, SPACINGS, DEFAULT_READING.spacing),
    theme: pick(r.theme, THEMES, DEFAULT_READING.theme),
    contrast: r.contrast === true,
    calm: r.calm === true,
    rate: Math.min(RATE_MAX, Math.max(RATE_MIN, Math.round(rate * 20) / 20)),
    voice: typeof r.voice === "string" && r.voice ? r.voice.slice(0, 300) : null,
  };
}

function load(): Reading {
  try {
    return parseReading(JSON.parse(localStorage.getItem(READING_KEY) ?? "{}"));
  } catch {
    // Private window, blocked site data or a hand-edited value: the defaults.
    return DEFAULT_READING;
  }
}

// ── Applying it to the page ────────────────────────────────────────────────

const matches = (query: string) => typeof window !== "undefined" && window.matchMedia(query).matches;

/** The attributes <html> carries for `r`: only those that differ from the page as designed. */
export function readingAttributes(r: Reading, device = { light: false, contrast: false }): Record<string, string | null> {
  const light = r.theme === "light" || (r.theme === "system" && device.light);
  return {
    "data-text": r.size === "default" ? null : r.size,
    "data-face": r.face === "default" ? null : r.face,
    "data-spacing": r.spacing === "normal" ? null : r.spacing,
    "data-theme": light ? "light" : null,
    "data-contrast": r.contrast || device.contrast ? "more" : null,
    "data-motion": r.calm ? "less" : null,
  };
}

function apply(r: Reading) {
  const root = document.documentElement;
  const attrs = readingAttributes(r, { light: matches(DEVICE_LIGHT), contrast: matches(DEVICE_CONTRAST) });
  for (const [name, value] of Object.entries(attrs)) {
    if (value === null) root.removeAttribute(name);
    else root.setAttribute(name, value);
  }
  // The browser's own bar follows the ground.
  const ground = getComputedStyle(root).getPropertyValue("--c-bg").trim();
  if (ground) document.querySelector('meta[name="theme-color"]')?.setAttribute("content", ground);
}

// ── The store ──────────────────────────────────────────────────────────────

let current: Reading | null = null;
const listeners = new Set<() => void>();

function snapshot(): Reading {
  if (current === null) current = load();
  return current;
}

function changed() {
  current = load();
  apply(current);
  listeners.forEach((l) => l());
}

let watching = false;

/** Other tabs' changes and the device's own settings, followed once the first view subscribes. */
function watch() {
  if (watching) return;
  watching = true;
  window.addEventListener("storage", (e) => {
    if (e.key === READING_KEY || e.key === null) changed();
  });
  for (const q of [DEVICE_LIGHT, DEVICE_CONTRAST]) window.matchMedia(q).addEventListener("change", () => apply(snapshot()));
  apply(snapshot());
}

function subscribe(listener: () => void) {
  watch();
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Change some settings on this device. */
export function setReading(change: Partial<Reading>) {
  const next = parseReading({ ...snapshot(), ...change });
  try {
    localStorage.setItem(READING_KEY, JSON.stringify(next));
  } catch {
    // Blocked storage: the change holds until the page is reloaded.
  }
  current = next;
  apply(next);
  listeners.forEach((l) => l());
}

/** This device's reading settings, kept current. The defaults until the page is on the client. */
export function useReading(): Reading {
  return useSyncExternalStore(subscribe, snapshot, () => DEFAULT_READING);
}

/** The settings as they stand now, outside React (Listen reads its rate and voice from here). */
export function readingNow(): Reading {
  return typeof window === "undefined" ? DEFAULT_READING : snapshot();
}

/** Less motion, by this device's setting here or the device's own: for motion drawn in code. */
export function lessMotion(): boolean {
  if (typeof window === "undefined") return false;
  return document.documentElement.getAttribute("data-motion") === "less" || matches(DEVICE_CALM);
}

/** How to scroll something into view: at once with less motion, else smoothly. */
export function scrollBehavior(): ScrollBehavior {
  return lessMotion() ? "auto" : "smooth";
}
