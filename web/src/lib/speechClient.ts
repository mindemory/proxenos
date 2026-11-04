"use client";

// Settings, Listening's side of the voices made on this Mac: where things stand (followed while a
// model downloads), getting a model, and the clip of the user's voice: recorded here or picked
// from a file, turned into the one shape the vault keeps (16-bit mono WAV at 24 kHz) in the
// browser, and sent to the page's own server, which keeps it in the vault. Nothing here goes
// anywhere else.

import { useCallback, useEffect, useState } from "react";

import type { SpeechChange, SpeechEngine, SpeechStatus, SpeechStatusResponse } from "./types";
import { JSON_HEADERS } from "./headers";

const POLL_MS = 1_000;
export const CLIP_RATE = 24_000;
export const CLIP_MIN = 5;
export const CLIP_MAX = 30;

async function post(url: string, body: object): Promise<SpeechChange> {
  try {
    const res = await fetch(url, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) });
    const answer = (await res.json().catch(() => ({}))) as Partial<SpeechChange> & { error?: string };
    return { ok: res.ok && answer.ok !== false, message: answer.message ?? answer.error ?? `It didn't work (${res.status}).` };
  } catch (e) {
    return { ok: false, message: e instanceof Error ? e.message : String(e) };
  }
}

/** Where the voices stand, kept current while a model downloads, and what changes them. */
export function useSpeechStatus() {
  const [status, setStatus] = useState<SpeechStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(
    () =>
      fetch("/api/speech", { cache: "no-store" })
        .then((res) => res.json() as Promise<SpeechStatusResponse>)
        .then(
          (answer) => {
            setStatus(answer.status);
            setError(answer.error);
          },
          (e: unknown) => setError(e instanceof Error ? e.message : String(e)),
        ),
    [],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  const downloading = status?.download?.state === "running";
  useEffect(() => {
    if (!downloading) return;
    const timer = window.setInterval(() => void reload(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [downloading, reload]);

  const getModel = async (engine: SpeechEngine) => {
    const said = await post("/api/speech", { get: engine });
    await reload();
    return said;
  };
  const saveClip = async (wav: Blob, text: string | null) => {
    const said = await post("/api/speech/clip", { wav: await base64(wav), text });
    await reload();
    return said;
  };
  const deleteClip = async () => {
    const said = await post("/api/speech/clip", { delete: true });
    await reload();
    return said;
  };
  return { status, error, reload, getModel, saveClip, deleteClip };
}

function base64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

// ── The clip ────────────────────────────────────────────────────────────────

/** Recording from the microphone. */
export interface Recording {
  /** The recording once it stops, by stop() or after the most seconds it was given; null when cancelled. */
  done: Promise<Blob | null>;
  stop(): void;
  cancel(): void;
}

export async function record(most: number): Promise<Recording> {
  // Echo cancellation and gain control change how a voice sounds; the room's hum is better gone.
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: false, autoGainControl: false, noiseSuppression: true },
  });
  const recorder = new MediaRecorder(stream);
  const parts: Blob[] = [];
  let cancelled = false;
  recorder.ondataavailable = (e) => {
    if (e.data.size) parts.push(e.data);
  };
  const end = () => {
    if (recorder.state !== "inactive") recorder.stop();
  };
  const timer = window.setTimeout(end, most * 1000);
  const done = new Promise<Blob | null>((resolve) => {
    recorder.onstop = () => {
      window.clearTimeout(timer);
      stream.getTracks().forEach((t) => t.stop());
      resolve(cancelled ? null : new Blob(parts, { type: recorder.mimeType }));
    };
  });
  recorder.start();
  return {
    done,
    stop: end,
    cancel: () => {
      cancelled = true;
      end();
    },
  };
}

/**
 * Any recording the browser can play, as the clip the vault keeps: mono, 24 kHz, 16-bit, with
 * silence at either end trimmed. Its length in seconds too, which must be CLIP_MIN to CLIP_MAX.
 */
export async function toClip(recording: Blob): Promise<{ wav: Blob; seconds: number }> {
  const context = new AudioContext();
  let decoded: AudioBuffer;
  try {
    decoded = await context.decodeAudioData(await recording.arrayBuffer());
  } finally {
    void context.close();
  }
  const frames = Math.max(1, Math.ceil(decoded.duration * CLIP_RATE));
  const offline = new OfflineAudioContext(1, frames, CLIP_RATE);
  const source = offline.createBufferSource();
  source.buffer = decoded;
  source.connect(offline.destination);
  source.start();
  const samples = trimmed((await offline.startRendering()).getChannelData(0));
  return { wav: wavOf(samples, CLIP_RATE), seconds: Math.round((samples.length / CLIP_RATE) * 10) / 10 };
}

/** Silence at either end cut to a quarter of a second. */
function trimmed(samples: Float32Array): Float32Array {
  const loud = 0.02;
  const keep = Math.round(CLIP_RATE / 4);
  let start = 0;
  while (start < samples.length && Math.abs(samples[start]) < loud) start++;
  let end = samples.length - 1;
  while (end > start && Math.abs(samples[end]) < loud) end--;
  if (start >= end) return samples;
  return samples.slice(Math.max(0, start - keep), Math.min(samples.length, end + keep));
}

function wavOf(samples: Float32Array, rate: number): Blob {
  const view = new DataView(new ArrayBuffer(44 + samples.length * 2));
  const text = (offset: number, s: string) => [...s].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  text(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((s, i) => view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7fff, true));
  return new Blob([view], { type: "audio/wav" });
}
