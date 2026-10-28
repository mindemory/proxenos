"use client";

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { formatDateTime, longDay } from "@/lib/format";
import { useMedia } from "@/lib/hooks";
import { dayOf, hasTime } from "@/lib/memoryMarks";
import { useMemoryContext } from "@/lib/memoryClient";
import type { MemoryRecord } from "@/lib/types";
import { cn } from "@/lib/utils";

import { MemorySourceBadge } from "./sources";

const SHOWN_CHARS = 1500;

function Record({ r, innerRef }: { r: MemoryRecord; innerRef?: React.Ref<HTMLLIElement> }) {
  const long = r.text.length > SHOWN_CHARS;
  return (
    <li
      ref={innerRef}
      aria-current={r.target ? "true" : undefined}
      className={cn("px-4 py-3", r.target ? "row-flash border-l-2 border-accent bg-accent/10" : "border-l-2 border-transparent")}
    >
      <div className="flex min-w-0 items-baseline gap-2 text-xs text-muted">
        <span className={cn("truncate", r.from_me ? "font-medium text-accent" : "text-ink/85")}>
          {r.from_me ? "You" : r.who.split(", ")[0] || "Someone"}
        </span>
        <span className="num ml-auto flex-shrink-0">
          {hasTime(r.ts) ? formatDateTime(r.ts) : longDay(r.ts.slice(0, 10))}
        </span>
      </div>
      {r.title && <p className="mt-0.5 break-words font-display text-base leading-snug text-ink">{r.title}</p>}
      {r.text && (
        <p className="mt-0.5 whitespace-pre-wrap break-words text-sm leading-relaxed text-ink/90">
          {long ? `${r.text.slice(0, SHOWN_CHARS)}…` : r.text}
        </p>
      )}
    </li>
  );
}

/**
 * The conversation around one search hit, as a panel beside the results (a full-screen sheet on a
 * phone). The hit itself is highlighted and scrolled into view.
 */
export function ContextPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const { data, error, loading } = useMemoryContext(id);
  const target = useRef<HTMLLIElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const beside = useMedia("(min-width: 768px)");

  // Bring the memory to the middle of the panel. Only the panel scrolls: scrollIntoView would
  // move the whole page too.
  useEffect(() => {
    const box = scroller.current;
    const row = target.current;
    if (box && row) box.scrollTop = row.offsetTop - (box.clientHeight - row.clientHeight) / 2;
  }, [data]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const hit = data?.records.find((r) => r.target);
  const place = hit?.where_ || hit?.who.split(", ")[0] || "";

  const panel = (
    <aside
      aria-label="Conversation around this memory"
      className="fixed inset-0 z-[60] flex flex-col bg-surface sheet-in md:sticky md:inset-auto md:top-14 md:z-auto md:h-[calc(100dvh-3.5rem)] md:w-[26rem] md:flex-shrink-0 md:self-start md:border-l md:border-line md:panel-in lg:w-[30rem]"
    >
      <div className="flex items-start gap-3 border-b border-line px-4 pb-3 pt-4">
        <div className="min-w-0 flex-1">
          {hit && <MemorySourceBadge source={hit.source} />}
          <h2 className="mt-1.5 break-words font-display text-xl leading-tight text-ink">{place || "Around this"}</h2>
          {hit && <p className="num text-xs text-muted">{longDay(dayOf(hit.ts))}</p>}
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="-m-1 rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-ink"
        >
          <X size={18} />
        </button>
      </div>

      <div ref={scroller} className="relative min-h-0 flex-1 overflow-y-auto overscroll-contain pb-6" aria-busy={loading}>
        {error && !data ? (
          <p className="p-4 text-sm text-bad-ink" role="alert">
            {error === "not found" ? "That memory is no longer in the index. Run proxenos index." : `Couldn't load it: ${error}`}
          </p>
        ) : !data ? (
          <div className="space-y-3 p-4" aria-hidden="true">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="h-12 animate-pulse rounded-lg bg-surface-2" />
            ))}
          </div>
        ) : (
          <ol className="divide-y divide-line">
            {data.records.map((r) => (
              <Record key={r.id} r={r} innerRef={r.target ? target : undefined} />
            ))}
          </ol>
        )}
      </div>
    </aside>
  );
  // Beside the results on a wide screen. On a phone it covers the page, which the animated view
  // around it would keep from reaching the screen's edges, so it goes straight into the body.
  return beside ? panel : createPortal(panel, document.body);
}
