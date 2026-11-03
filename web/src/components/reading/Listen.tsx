"use client";

import { useEffect } from "react";
import { Pause, Play, Square, Volume2 } from "lucide-react";

import { useReading } from "@/lib/reading";
import { pause, play, resume, stopIf, stop, useSpeech, warm } from "@/lib/speech";
import { cn } from "@/lib/utils";

const PILL =
  "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[0.8125rem] leading-none whitespace-nowrap transition-colors";

/**
 * Listen: reads `text` aloud with the voice chosen in Settings (one made on this Mac, or this
 * device's own), with Pause and Stop while it reads. Shows nothing where there's no voice to read
 * with, and stops when it goes away (another view opened), so speech never outlives what it reads.
 */
export function Listen({
  id,
  text,
  what,
  label = "Listen",
  className,
}: {
  id: string;
  text: string;
  /** What's read, for a screen reader: "where things stand". */
  what?: string;
  label?: string;
  className?: string;
}) {
  const speech = useSpeech();
  const { engine } = useReading();
  useEffect(() => () => stopIf(id), [id]);
  useEffect(() => {
    if (engine !== "device") warm();
  }, [engine]);
  if (!(speech.available || engine !== "device") || !text.trim()) return null;

  if (speech.playing !== id) {
    return (
      <button
        type="button"
        onClick={() => play(id, text)}
        aria-label={what ? `${label}: ${what}` : undefined}
        className={cn(PILL, "border-line-strong text-muted hover:bg-surface-2 hover:text-ink", className)}
      >
        <Volume2 size={14} strokeWidth={2.25} aria-hidden="true" />
        {label}
      </button>
    );
  }

  return (
    <span
      role="group"
      aria-label={what ? `Reading ${what} aloud` : "Reading aloud"}
      aria-busy={speech.waiting}
      className={cn("inline-flex items-center gap-1.5", className)}
    >
      <button
        type="button"
        onClick={() => (speech.paused ? resume() : pause())}
        className={cn(PILL, "border-accent/40 bg-accent/10 text-accent")}
      >
        {speech.paused ? <Play size={14} strokeWidth={2.25} aria-hidden="true" /> : <Pause size={14} strokeWidth={2.25} aria-hidden="true" />}
        {speech.paused ? "Resume" : "Pause"}
      </button>
      <button type="button" onClick={stop} className={cn(PILL, "border-line-strong text-muted hover:bg-surface-2 hover:text-ink")}>
        <Square size={12} strokeWidth={2.5} aria-hidden="true" />
        Stop
      </button>
      {speech.waiting && !speech.paused && <span className="text-xs text-muted">Getting the voice ready…</span>}
    </span>
  );
}
