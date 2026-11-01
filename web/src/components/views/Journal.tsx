"use client";

import { useState } from "react";
import { NotebookPen, RefreshCw } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { EmptyState, ErrorBanner, NoVault } from "@/components/EmptyState";
import { ProseSkeleton } from "@/components/Skeleton";
import { useJournal } from "@/lib/client";
import { formatDateTime, longDay, timeAgo } from "@/lib/format";
import { JOURNAL_SECTIONS, type JournalSection } from "@/lib/types";
import { cn } from "@/lib/utils";

const HEADINGS: Record<JournalSection, { label: string; note: string }> = {
  done: { label: "Done", note: "Tasks closed, messages sent, steps accepted, forms filled." },
  said: { label: "Said", note: "Where you wrote, and what you told Proxenos." },
  moved: { label: "Moved", note: "Your projects' code, on any branch." },
  waiting: { label: "Waiting", note: "On someone else." },
  next: { label: "Next", note: "Tomorrow's calendar, what's due, and what's waiting to be sent." },
};

/**
 * The day, written down: a few sentences on how it went and what's next, then the day's lines,
 * all from what Proxenos already tracks. The night job writes the day that just ended; "Write
 * today's" writes today so far.
 */
export function Journal() {
  const [date, setDate] = useState<string | null>(null);
  const { data, error, writing, writeToday, clearError } = useJournal(date);

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load the journal: ${error}`} /> : <ProseSkeleton label="Loading the journal" />;
  }
  if (!data.vault.exists) return <NoVault path={data.vault.path} />;

  const write = (
    <ActionButton
      icon={RefreshCw}
      label={writing ? "Writing… a minute or two" : "Write today's"}
      tone="accent"
      active={!writing}
      onClick={() => {
        if (writing) return;
        setDate(null);
        void writeToday();
      }}
    />
  );

  if (!data.entry) {
    return (
      <div className="p-4 sm:p-6">
        {error && <ErrorBanner message={error} onDismiss={clearError} />}
        <EmptyState icon={NotebookPen} title="No journal yet" command="proxenos clone journal --date today">
          Each night Proxenos writes down the day that ended: what got done, where you wrote, what moved in your projects, what&apos;s
          waiting on others and what&apos;s next, from what it already tracks. Nothing to narrate.
        </EmptyState>
        <div className="mt-4">{write}</div>
      </div>
    );
  }

  const { entry } = data;
  const switching = date !== null && data.date !== date;

  return (
    <div className="pb-24 md:pb-20">
      {error && <ErrorBanner message={error} onDismiss={clearError} />}

      <div className="px-4 sm:px-6 py-3 border-b border-line flex flex-wrap items-center justify-between gap-x-4 gap-y-2 text-sm text-muted">
        <label className="inline-flex items-center gap-2">
          <span>Day</span>
          <select
            value={data.date ?? ""}
            onChange={(e) => setDate(e.target.value)}
            className="num bg-surface border border-line-strong rounded-full px-3 py-1 text-sm text-ink hover:border-accent/40"
          >
            {data.dates.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-center gap-3">
          {entry.generated && (
            <span title={formatDateTime(entry.generated)}>
              Written <span className="num">{timeAgo(entry.generated, data.now)}</span>
            </span>
          )}
          {write}
        </div>
      </div>

      <article className={cn("p-4 sm:p-6 space-y-8 max-w-3xl transition-opacity", switching && "opacity-50")} aria-busy={switching}>
        <header className="space-y-3">
          <p className="smallcaps">{longDay(`${entry.date}T12:00:00`)}</p>
          {entry.brief ? (
            <p className="font-display text-xl leading-relaxed text-ink">{entry.brief}</p>
          ) : (
            <p className="text-sm text-muted">No summary for this day: the model wasn&apos;t set up or didn&apos;t answer. The lines below are all there.</p>
          )}
          {entry.next_up.length > 0 && (
            <div className="card p-4">
              <p className="eyebrow mb-2">Next up</p>
              <ol className="list-decimal space-y-1 pl-5 text-sm text-ink">
                {entry.next_up.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ol>
            </div>
          )}
        </header>

        {JOURNAL_SECTIONS.map((s) =>
          entry.sections[s].length > 0 ? (
            <section key={s} aria-label={HEADINGS[s].label} className="space-y-2">
              <div>
                <h2 className="smallcaps text-accent">{HEADINGS[s].label}</h2>
                <p className="text-xs text-muted">{HEADINGS[s].note}</p>
              </div>
              <ul className="space-y-1.5 text-sm text-ink/90">
                {entry.sections[s].map((line, i) => (
                  <li key={`${s}-${i}`} className="break-words">
                    {line}
                  </li>
                ))}
              </ul>
            </section>
          ) : null,
        )}
      </article>
    </div>
  );
}
