"use client";

// Reading aloud, one thing at a time, a sentence or two at a time.
//
// With a voice made on this Mac (Settings, Listening: the natural voice or the user's own, by
// proxenos.speech), each sentence goes to the page's own server, which has the speech server on
// 127.0.0.1 make it, and comes back as sound. The next AHEAD are asked for while one plays, so a
// long text starts after its first sentence and runs on without waiting. Whenever that voice
// can't (not installed, not downloaded, no clip, or it fails), Listen goes on with the browser's
// own speech from the sentence it was on, and keeps to it for RETRY_MS before asking again.
//
// The browser's own speech (speechSynthesis) speaks on this device too. Some browsers also offer
// voices that are made on a server (Chrome's "Google" voices, Edge's "Online" ones), so only
// voices the browser marks as local (localService) are used; with none, and no voice made on this
// Mac chosen, Listen doesn't show. Long utterances stall in some browsers, and pausing then
// starting again from the current sentence works everywhere, which speechSynthesis.pause doesn't.

import { useSyncExternalStore } from "react";

import { type Engine, readingNow } from "./reading";
import { JSON_HEADERS } from "./headers";

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
  /** Waiting for a voice made on this Mac to make the sentence it's on. */
  waiting: boolean;
}

const NONE: SpeechState = { available: false, voices: [], playing: null, paused: false, waiting: false };

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
// What's reading this queue: the device's speech, or a voice made on this Mac.
let via: Engine = "device";

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

// ── The device's own speech ────────────────────────────────────────────────

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

// ── A voice made on this Mac ───────────────────────────────────────────────

const AHEAD = 2;
const RETRY_MS = 60_000;
let downUntil = 0;
let player: HTMLAudioElement | null = null;
let playingUrl: string | null = null;
let asking: AbortController | null = null;
const made = new Map<number, Promise<Blob | null>>();
// Where in its sentence a pause stopped, to resume from there.
let resumeFrom = 0;

/** The voice this reading starts with: the one chosen, unless it failed a moment ago. */
function engineNow(): Engine {
  const chosen = readingNow().engine;
  return chosen !== "device" && Date.now() < downUntil ? "device" : chosen;
}

const WARM_MS = 10 * 60_000; // under the speech server's own 15 minutes idle
const warmed = new Map<Engine, number>();

/**
 * Have the voice chosen loaded on this Mac, as a view with Listen opens, so its first sentence
 * comes in a moment rather than after the model loads. Once in WARM_MS at most.
 */
export function warm() {
  const engine = engineNow();
  if (engine === "device" || Date.now() - (warmed.get(engine) ?? 0) < WARM_MS) return;
  warmed.set(engine, Date.now());
  void fetch("/api/speech", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ warm: engine, voice: engine === "natural" ? readingNow().natural : null }),
  }).catch(() => {});
}

/** Sentence `i` as sound, asked for once per reading; null when the voice couldn't make it. */
function sound(i: number): Promise<Blob | null> {
  let p = made.get(i);
  if (!p) {
    const r = readingNow();
    p = fetch("/api/speech/say", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ text: queue[i], engine: via, voice: via === "natural" ? r.natural : null }),
      signal: asking?.signal,
    })
      .then((res) => (res.ok ? res.blob() : null))
      .catch(() => null);
    made.set(i, p);
  }
  return p;
}

/** A hundredth of a second of silence, as a WAV. */
function silence(): string {
  const samples = 240;
  const view = new DataView(new ArrayBuffer(44 + samples * 2));
  const text = (offset: number, s: string) => [...s].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  text(0, "RIFF");
  view.setUint32(4, 36 + samples * 2, true);
  text(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, 24000, true);
  view.setUint32(28, 48000, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, samples * 2, true);
  return URL.createObjectURL(new Blob([view], { type: "audio/wav" }));
}

/** Play a moment of silence from the click itself, so the browser lets the sentences that follow play. */
function unlock() {
  player ??= new Audio();
  const url = silence();
  player.src = url;
  player
    .play()
    .catch(() => {})
    .finally(() => URL.revokeObjectURL(url));
}

/** Stop the sound and forget what was made for this reading. */
function release() {
  asking?.abort();
  asking = null;
  made.clear();
  if (player) {
    player.onended = null;
    player.onerror = null;
    player.onloadedmetadata = null;
    player.pause();
  }
  if (playingUrl) URL.revokeObjectURL(playingUrl);
  playingUrl = null;
}

/** The voice made on this Mac couldn't: go on with the device's, from this sentence. */
function fallBack(mine: number) {
  downUntil = Date.now() + RETRY_MS;
  via = "device";
  release();
  set({ waiting: false });
  if (synth() && voiceFor(readingNow().voice)) speakNext(mine);
  else stop();
}

async function playMade(mine: number) {
  if (at >= queue.length) return stop();
  const blob = await sound(at);
  if (mine !== turn) return;
  if (!blob) return fallBack(mine);
  for (let i = at + 1; i <= at + AHEAD && i < queue.length; i++) void sound(i);
  const p = (player ??= new Audio());
  if (playingUrl) URL.revokeObjectURL(playingUrl);
  playingUrl = URL.createObjectURL(blob);
  const from = resumeFrom;
  resumeFrom = 0;
  p.onloadedmetadata = () => {
    p.playbackRate = readingNow().rate;
    if (from > 0 && from < p.duration) p.currentTime = from;
  };
  p.onended = () => {
    if (mine !== turn) return;
    at += 1;
    void playMade(mine);
  };
  p.onerror = () => {
    if (mine === turn) fallBack(mine);
  };
  p.preservesPitch = true;
  p.src = playingUrl;
  p.playbackRate = readingNow().rate;
  set({ waiting: false });
  p.play().catch(() => {
    if (mine === turn) fallBack(mine);
  });
}

// ── Reading ────────────────────────────────────────────────────────────────

function begin() {
  const mine = ++turn;
  if (via !== "device") {
    set({ waiting: true });
    void playMade(mine);
    return;
  }
  const s = synth();
  if (!s) return stop();
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
  if (parts.length === 0) return;
  release();
  via = engineNow();
  if (via === "device" && !synth()) return;
  if (via !== "device") {
    synth()?.cancel();
    asking = new AbortController();
    unlock();
  }
  queue = parts;
  at = 0;
  resumeFrom = 0;
  set({ playing: id, paused: false });
  begin();
}

/** Pause where it is: a voice made on this Mac resumes mid-sentence, the device's from the sentence's start. */
export function pause() {
  if (state.playing === null || state.paused) return;
  turn += 1;
  if (via !== "device") {
    if (player && playingUrl && !player.ended) resumeFrom = player.currentTime;
    player?.pause();
  } else {
    synth()?.cancel();
  }
  set({ paused: true, waiting: false });
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
  resumeFrom = 0;
  release();
  synth()?.cancel();
  if (state.playing !== null || state.paused || state.waiting) set({ playing: null, paused: false, waiting: false });
}

/** Stop, if what's being read is `id`: its control is going away. */
export function stopIf(id: string) {
  if (state.playing === id) stop();
}

/** Whether this device can read aloud, its voices, and what's being read, kept current. */
export function useSpeech(): SpeechState {
  return useSyncExternalStore(subscribe, () => state, () => NONE);
}
