"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, ImageIcon } from "lucide-react";

import { cn } from "@/lib/utils";

// A long question is clipped until asked for, so a page of answers stays scannable.
const CLIP_CHARS = 600;
const CLIP_LINES = 8;

/** The question as it was written: one line stays one line, a pasted message keeps its breaks. */
export function QuestionText({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const long = text.length > CLIP_CHARS || text.split("\n").length > CLIP_LINES;
  return (
    <div className="relative min-w-0">
      <p className={cn("whitespace-pre-wrap break-words leading-relaxed text-ink/90", long && !expanded && "max-h-40 overflow-hidden")}>
        {text}
      </p>
      {long && !expanded && (
        <div className="pointer-events-none absolute inset-x-0 bottom-6 h-12 bg-gradient-to-t from-surface to-transparent" />
      )}
      {long && (
        <button
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="relative mt-1 inline-flex items-center gap-1 text-xs text-accent hover:underline underline-offset-4"
        >
          <ChevronDown size={13} className={cn("transition-transform", expanded && "rotate-180")} />
          {expanded ? "Show less" : "Show all"}
        </button>
      )}
    </div>
  );
}

/** How many screenshots came with a question. */
export function ShotCount({ n }: { n: number }) {
  if (n <= 0) return null;
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-md border border-line-strong bg-surface-2 px-1.5 py-0.5 text-xs text-ink/90">
      <ImageIcon size={12} aria-hidden="true" />
      <span className="num">{n}</span> {n === 1 ? "screenshot" : "screenshots"}
    </span>
  );
}

/** A heading that opens its text, closed until asked for. */
export function Fold({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="inline-flex items-center gap-1 text-sm text-muted transition-colors hover:text-ink"
      >
        <ChevronRight size={15} className={cn("transition-transform", open && "rotate-90")} aria-hidden="true" />
        {label}
      </button>
      {open && <div className="mt-2 border-l-2 border-line-strong pl-3">{children}</div>}
    </div>
  );
}
