"use client";

// Reading aloud with the browser's own speech (speechSynthesis), so the words are spoken on this
// device and never sent anywhere. Some browsers also offer voices that are made on a server
// (Chrome's "Google" voices, Edge's "Online" ones), so only voices the browser marks as local
// (localService) are used; with none, Listen doesn't show. One thing is read at a time, a
// sentence or two per utterance: long utterances stall in some browsers, and pausing then
// starting again from the current sentence works everywhere, which speechSynthesis.pause doesn't.

import { useSyncExternalStore } from "react";

import { readingNow } from "./reading";

export interface Voice {
  id: string; // its voiceURI
  name: string;
  lang: string;
  /** The voice this device reads with unless told otherwise. */
  system: boolean;
}

export interface SpeechState {
  /** Whether this browser can read aloud here, with a voice on this device. */
  available: boolean;
  /** This device's voices, those in the page's language first. */
  voices: Voice[];
  /** What's being read: the id its Listen control gave, or null. */
  playing: string | null;
  paused: boolean;
}

const NONE: SpeechState = { available: false, voices: [], playing: null, paused: false };

const synth = (): SpeechSynthesis | null =>
  typeof window !== "undefined" && "speechSynthesis" in window && "SpeechSynthesisUtterance" in window ? window.speechSynthesis : null;

function localVoices(): SpeechSynthesisVoice[] {
  try {
    return synth()?.getVoices().filter((v) => v.localService) ?? [];
  } catch {
    return [];
  }
}

const language = () => (typeof navigator !== "undefined" ? navigator.language : "en").slice(0, 2).toLowerCase();

function listVoices(): Voice[] {
  const lang = language();
  return localVoices()
    .map((v) => ({ id: v.voiceURI, name: v.name, lang: v.lang, system: v.default }))
    .sort((a, b) => {
      const own = Number(b.lang.toLowerCase().startsWith(lang)) - Number(a.lang.toLowerCase().startsWith(lang));
      return own || a.name.localeCompare(b.name);
    });
}

/** The voice to read with: the one picked here, else the system's when it's local, else one in the page's language. */
function voiceFor(wanted: string | null): SpeechSynthesisVoice | null {
  const voices = localVoices();
  const lang = language();
  return (
    voices.find((v) => wanted !== null && v.voiceURI === wanted) ??
    voices.find((v) => v.default) ??
    voices.find((v) => v.lang.toLowerCase().startsWith(lang)) ??
    voices[0] ??
    null
  );
}

// ── Text for the ear ───────────────────────────────────────────────────────

/** Markdown and links taken out, so the voice reads the words and not the marks. */
export function speakable(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "a link")
    .replace(/^\s{0,3}(?:#{1,6}|>|[-*+]|\d+[.)])\s+/gm, "")
    .replace(/(\*\*|__|\*|`|~~)(?=\S)([\s\S]*?\S)\1/g, "$2")
    .replace(/(?<!\w)_(?=\S)(.*?\S)_(?!\w)/g, "$1")
    .replace(/\|/g, ", ")
    .replace(/[ \t]+/g, " ")
    .replace(/\s*\n\s*/g, "\n")
    .trim();
}

const CHUNK = 220;

/** Sentences, joined up to about CHUNK characters; a longer one is cut at a comma or a space. */
export function chunks(text: string): string[] {
  const sentences = text.split(/(?<=[.!?…])\s+|\n+/).map((s) => s.trim()).filter(Boolean);
  const out: string[] = [];
  for (let s of sentences) {
    while (s.length > CHUNK) {
      const comma = s.lastIndexOf(", ", CHUNK);
      const space = s.lastIndexOf(" ", CHUNK);
      const end = comma > CHUNK / 3 ? comma + 1 : space > CHUNK / 3 ? space : CHUNK;
      out.push(s.slice(0, end).trim());
      s = s.slice(end).trim();
    }
    const last = out.length - 1;
    // A heading or a list line has no stop of its own: give it one, so the voice pauses there.
    if (last >= 0 && out[last].length + s.length + 2 <= CHUNK) out[last] += `${/[.!?…:;,]$/.test(out[last]) ? "" : "."} ${s}`;
    else if (s) out.push(s);
  }
  return out;
}

// ── The store ──────────────────────────────────────────────────────────────

let state: SpeechState = NONE;
const listeners = new Set<() => void>();
let queue: string[] = [];
let at = 0;
// Bumped by every start, pause and stop, so an utterance cut short doesn't move the queue on.
let turn = 0;

function set(change: Partial<SpeechState>) {
  state = { ...state, ...change };
  listeners.forEach((l) => l());
}

function refreshVoices() {
  const voices = listVoices();
  set({ voices, available: voices.length > 0 });
}

let watching = false;

function subscribe(listener: () => void) {
  const s = synth();
  if (s && !watching) {
    watching = true;
    s.addEventListener("voiceschanged", refreshVoices);
    // Chrome lists its voices a moment after the page loads; Safari and Firefox at once.
    refreshVoices();
    // Some browsers go on reading after the page is reloaded or closed.
    window.addEventListener("pagehide", stop);
  }
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function speakNext(mine: number) {
  const s = synth();
  const voice = voiceFor(readingNow().voice);
  if (!s || !voice || at >= queue.length) return stop();
  const u = new SpeechSynthesisUtterance(queue[at]);
  u.voice = voice;
  u.lang = voice.lang;
  u.rate = readingNow().rate;
  u.onend = () => {
    if (mine !== turn) return;
    at += 1;
    speakNext(mine);
  };
  u.onerror = (e) => {
    if (mine !== turn || e.error === "interrupted" || e.error === "canceled") return;
    stop();
  };
  s.speak(u);
}

function begin() {
  const s = synth();
  if (!s) return;
  const mine = ++turn;
  if (s.speaking || s.pending) {
    s.cancel();
    // Some browsers drop an utterance queued in the same moment as a cancel.
    window.setTimeout(() => mine === turn && speakNext(mine), 80);
  } else {
    speakNext(mine);
  }
}

/** Read `text` aloud as `id`, from the start, stopping anything else being read. */
export function play(id: string, text: string) {
  const parts = chunks(speakable(text));
  if (!synth() || parts.length === 0) return;
  queue = parts;
  at = 0;
  set({ playing: id, paused: false });
  begin();
}

/** Stop where it is; resuming starts again from the sentence it was on. */
export function pause() {
  if (state.playing === null || state.paused) return;
  turn += 1;
  synth()?.cancel();
  set({ paused: true });
}

export function resume() {
  if (state.playing === null || !state.paused) return;
  set({ paused: false });
  begin();
}

export function stop() {
  turn += 1;
  queue = [];
  at = 0;
  synth()?.cancel();
  if (state.playing !== null || state.paused) set({ playing: null, paused: false });
}

/** Stop, if what's being read is `id`: its control is going away. */
export function stopIf(id: string) {
  if (state.playing === id) stop();
}

/** Whether this device can read aloud, its voices, and what's being read, kept current. */
export function useSpeech(): SpeechState {
  return useSyncExternalStore(subscribe, () => state, () => NONE);
}
