"use client";

import { useEffect, useMemo, useState } from "react";
import { Brain, Search, X } from "lucide-react";

import { EmptyState, ErrorBanner } from "@/components/EmptyState";
import { ResultSkeleton } from "@/components/Skeleton";
import { ContextPanel } from "@/components/memory/ContextPanel";
import { ResultRow } from "@/components/memory/ResultRow";
import { MemorySourceIcon, memorySourceLabel } from "@/components/memory/sources";
import { longDay } from "@/lib/format";
import { useDebounced, useMemorySearch } from "@/lib/memoryClient";
import { dayOf } from "@/lib/memoryMarks";
import type { MemoryHit } from "@/lib/types";
import { cn } from "@/lib/utils";

/** A search or a record to open, handed over from the command box or the home page. */
export interface MemoryIntent {
  q: string;
  id: string | null;
}

interface MemoryProps {
  initial: MemoryIntent | null;
  /** Called once the view has taken `initial`, so a later visit starts clean. */
  onConsumed: () => void;
}

const FIELD =
  "h-9 min-w-0 rounded-lg border border-line-strong bg-surface px-3 text-sm text-ink placeholder:text-muted/80 focus:border-accent/60 focus:outline-none";

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-1 text-xs transition-colors",
        active ? "border-accent/50 bg-accent/15 text-ink" : "border-line text-muted hover:border-line-strong hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

/** Hits grouped by the day they happened, newest day first; within a day, best match first. */
function byDay(hits: MemoryHit[]): [string, MemoryHit[]][] {
  const days = new Map<string, MemoryHit[]>();
  for (const h of hits) {
    const day = dayOf(h.ts);
    days.set(day, [...(days.get(day) ?? []), h]);
  }
  return [...days].sort((a, b) => b[0].localeCompare(a[0]));
}

/** Search over everything in raw/: messages, mail, calendar, notes, browsing and the rest. */
export function Memory({ initial, onConsumed }: MemoryProps) {
  const [text, setText] = useState(initial?.q ?? "");
  const [sources, setSources] = useState<string[]>([]);
  const [who, setWho] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [openId, setOpenId] = useState<string | null>(initial?.id ?? null);
  // The intent has been taken above; let the page forget it so a later visit starts clean.
  useEffect(() => {
    onConsumed();
  }, [onConsumed]);

  // Typing waits for a pause; the filters apply as they are set.
  const q = useDebounced(text.trim(), 300);
  const person = useDebounced(who.trim(), 300);
  const query = useMemo(() => ({ q, sources, who: person, since, until }), [q, sources, person, since, until]);
  const { data, error, loading } = useMemorySearch(query);

  const filtered = Boolean(q || person || sources.length || since || until);
  const groups = useMemo(() => byDay(data?.hits ?? []), [data]);
  const toggle = (source: string) =>
    setSources((s) => (s.includes(source) ? s.filter((x) => x !== source) : [...s, source]));
  const clear = () => {
    setText("");
    setSources([]);
    setWho("");
    setSince("");
    setUntil("");
  };

  return (
    <div className="flex min-h-[calc(100dvh-6.75rem)]">
      <div className="min-w-0 flex-1">
        <div className="sticky top-14 z-20 space-y-3 border-b border-line bg-bg/90 px-4 py-3 backdrop-blur-md sm:px-6">
          <form role="search" onSubmit={(e) => e.preventDefault()} className="relative">
            <Search size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
            <input
              type="search"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Search everything: words, “a phrase”, or pre*"
              aria-label="Search your memory"
              autoComplete="off"
              spellCheck={false}
              autoFocus={!initial?.id}
              className={cn(FIELD, "h-11 w-full rounded-xl pl-10 text-[15px]")}
            />
          </form>

          {data && data.facets.length > 0 && (
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Sources">
              <Chip active={sources.length === 0} onClick={() => setSources([])}>
                All
                <span className="num text-muted">
                  {data.facets.reduce((n, f) => n + f.count, 0).toLocaleString()}
                </span>
              </Chip>
              {data.facets.map((f) => (
                <Chip key={f.source} active={sources.includes(f.source)} onClick={() => toggle(f.source)}>
                  <MemorySourceIcon source={f.source} />
                  {memorySourceLabel(f.source)}
                  <span className="num text-muted">{f.count.toLocaleString()}</span>
                </Chip>
              ))}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <input
              value={who}
              onChange={(e) => setWho(e.target.value)}
              placeholder="Person"
              aria-label="Filter by person"
              autoComplete="off"
              spellCheck={false}
              className={cn(FIELD, "w-36 sm:w-44")}
            />
            <label className="flex items-center gap-1.5 text-xs text-muted">
              From
              <input type="date" value={since} max={until || undefined} onChange={(e) => setSince(e.target.value)} className={cn(FIELD, "w-[9.5rem]")} />
            </label>
            <label className="flex items-center gap-1.5 text-xs text-muted">
              To
              <input type="date" value={until} min={since || undefined} onChange={(e) => setUntil(e.target.value)} className={cn(FIELD, "w-[9.5rem]")} />
            </label>
            {filtered && (
              <button onClick={clear} className="inline-flex items-center gap-1 rounded text-xs text-accent underline-offset-4 hover:underline">
                <X size={12} />
                Clear
              </button>
            )}
            {data?.indexed && filtered && (
              <span className="num ml-auto text-xs text-muted" aria-live="polite">
                {data.total?.toLocaleString()} {data.total === 1 ? "match" : "matches"}
                {data.hits.length < (data.total ?? 0) && ` · best ${data.hits.length}`} · {data.took_ms} ms
              </span>
            )}
          </div>
        </div>

        {error && !data ? (
          <ErrorBanner message={`Couldn't search: ${error}`} />
        ) : !data ? (
          <ResultSkeleton />
        ) : !data.indexed ? (
          <EmptyState icon={Brain} title="Nothing is indexed yet" command="proxenos index">
            Memory search reads an index of everything in the vault. Build it once, and syncs keep it current.
          </EmptyState>
        ) : !filtered ? (
          <EmptyState icon={Search} title="Search everything you've said, read and received">
            Type a name, a word or a “phrase in quotes”. End a word with * to match its beginnings. Narrow it by source,
            person or date above.
          </EmptyState>
        ) : data.hits.length === 0 ? (
          <p className="px-4 py-12 text-center text-muted sm:px-6">{loading ? "Searching…" : "Nothing matches."}</p>
        ) : (
          <div className={cn("pb-24 md:pb-12", loading && "opacity-60 transition-opacity")} aria-busy={loading}>
            {error && <ErrorBanner message={error} />}
            {groups.map(([day, hits]) => (
              <section key={day} aria-label={longDay(day)}>
                <h2 className="eyebrow border-b border-line bg-surface/60 px-4 py-1.5 sm:px-6">
                  {longDay(day)} <span className="num ml-1 text-muted/80">{hits.length}</span>
                </h2>
                <ul className="divide-y divide-line border-b border-line">
                  {hits.map((h) => (
                    <ResultRow key={h.id} hit={h} active={h.id === openId} onOpen={() => setOpenId(h.id)} />
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </div>

      {openId && <ContextPanel key={openId} id={openId} onClose={() => setOpenId(null)} />}
    </div>
  );
}
