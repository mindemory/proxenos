import { sourceStyle } from "@/components/SourceBadge";
import { hasTime, plain, sameText } from "@/lib/memoryMarks";
import type { MemoryHit } from "@/lib/types";
import { cn } from "@/lib/utils";

import { Marked } from "./Marked";
import { MemorySourceBadge } from "./sources";

function timeOf(ts: string): string {
  if (!hasTime(ts)) return "";
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

/** Who and where as one short line. A chat is both who (its name is among the names) and where, so it's said once. */
export function whoWhere(hit: MemoryHit): string {
  const names = hit.who
    .split(", ")
    .filter((n) => n && n !== hit.where_)
    .slice(0, 3)
    .join(", ");
  if (!hit.where_) return names;
  return names ? `${names} · ${hit.where_}` : hit.where_;
}

/** One search hit: its source, who and where, its title, and the snippet with matched words marked. */
export function ResultRow({ hit, active, onOpen }: { hit: MemoryHit; active: boolean; onOpen: () => void }) {
  const showTitle = hit.title && !sameText(hit.snippet, hit.title);
  const time = timeOf(hit.ts);
  return (
    <li>
      <button
        onClick={onOpen}
        aria-current={active ? "true" : undefined}
        style={sourceStyle(hit.source)}
        className={cn(
          "block w-full border-l-2 px-4 py-3 text-left transition-colors hover:bg-surface-2 sm:px-6",
          active ? "border-accent bg-accent/10" : "border-transparent hover:border-[color-mix(in_oklab,var(--src)_70%,transparent)]",
        )}
      >
        <span className="flex min-w-0 items-center gap-2 text-xs text-muted">
          <MemorySourceBadge source={hit.source} />
          {hit.from_me && <span className="eyebrow flex-shrink-0 text-accent">You</span>}
          <span className="min-w-0 flex-1 truncate">{whoWhere(hit)}</span>
          {time && <span className="num flex-shrink-0">{time}</span>}
        </span>
        {showTitle && <span className="mt-1 block break-words font-display text-lg leading-snug text-ink">{hit.title}</span>}
        {plain(hit.snippet).trim() && (
          <span className="mt-1 line-clamp-3 break-words text-sm leading-relaxed text-ink/85">
            <Marked text={hit.snippet} />
          </span>
        )}
      </button>
    </li>
  );
}
