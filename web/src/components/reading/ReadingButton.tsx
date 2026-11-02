"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ALargeSmall, ArrowRight } from "lucide-react";

import { cn } from "@/lib/utils";

import { ReadingControls } from "./ReadingControls";

/**
 * The header's Aa: text size, typeface, spacing, theme, contrast and motion from any view, in a
 * small panel, with the voice and its speed a step away in Settings. Escape or a click outside
 * closes it, and focus goes back to the button.
 */
export function ReadingButton({ onSettings }: { onSettings: () => void }) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    panel.current?.querySelector<HTMLElement>("button")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    };
    const onPointer = (e: PointerEvent) => {
      const t = e.target instanceof Node ? e.target : null;
      if (t && !panel.current?.contains(t) && !button.current?.contains(t)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  return (
    <div className="relative">
      <button
        ref={button}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-haspopup="dialog"
        aria-label="Reading: text size, typeface, theme and contrast"
        title="Reading"
        className={cn(
          "flex h-9 w-9 items-center justify-center rounded-full border border-line-strong text-muted transition-colors hover:bg-surface hover:text-ink",
          open && "bg-surface-2 text-ink",
        )}
      >
        <ALargeSmall size={17} aria-hidden="true" />
      </button>
      {open && (
        <div
          ref={panel}
          id={id}
          role="dialog"
          aria-label="Reading"
          // Across the screen on a phone, where the button isn't at the edge; under it from sm on.
          className="fade-in fixed inset-x-3 top-[3.75rem] z-50 max-h-[calc(100dvh-5rem)] overflow-y-auto overscroll-contain rounded-2xl border border-line-strong bg-surface p-4 shadow-pop sm:absolute sm:inset-x-auto sm:right-0 sm:top-11 sm:w-[22rem]"
        >
          <p className="smallcaps mb-3">Reading</p>
          <ReadingControls compact />
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              onSettings();
            }}
            className="mt-4 inline-flex items-center gap-1.5 text-sm text-accent underline-offset-4 hover:underline"
          >
            Listen&apos;s voice and speed, in Settings
            <ArrowRight size={14} aria-hidden="true" />
          </button>
        </div>
      )}
    </div>
  );
}
