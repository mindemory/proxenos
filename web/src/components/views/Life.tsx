"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, CalendarDays, Library, PenLine, RefreshCw } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { EmptyState, ErrorBanner, NoVault } from "@/components/EmptyState";
import { Segmented } from "@/components/layout/Segmented";
import { ProseSkeleton } from "@/components/Skeleton";
import { monthName, useLife } from "@/lib/client";
import { formatDateTime, longDay, timeAgo } from "@/lib/format";
import type { LifeDay, LifeMonth, LifeResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

type Listed = "events" | "notes" | "activity" | "health" | "other";

const PARTS: { key: Listed; label: string }[] = [
  { key: "events", label: "Calendar" },
  { key: "notes", label: "Wrote down" },
  { key: "activity", label: "Activity" },
  { key: "health", label: "Health records" },
  { key: "other", label: "Also" },
];

/** "March" from "2026-03". */
function monthOnly(month: string): string {
  return monthName(month).split(" ")[0];
}

interface WriteProps {
  month: string;
  /** The month being written now, if any: one at a time. */
  writing: string | null;
  again?: boolean;
  onWrite: (month: string) => void;
}

function WriteButton({ month, writing, again = false, onWrite }: WriteProps) {
  const mine = writing === month;
  return (
    <ActionButton
      icon={again ? RefreshCw : PenLine}
      label={mine ? "Writing… a few minutes" : again ? "Write again" : "Write this month"}
      tone="accent"
      active={mine || !again}
      disabled={writing !== null}
      onClick={() => onWrite(month)}
    />
  );
}

/** A month in a year's list: its story's opening and highlights, or "Not written yet". */
function MonthCard({ m, writing, onOpen, onWrite }: { m: LifeMonth; writing: string | null; onOpen: () => void; onWrite: (month: string) => void }) {
  return (
    <article className="card card-hover flex flex-col gap-3 p-4 sm:p-5">
      <div className="flex items-baseline justify-between gap-3">
        <button type="button" onClick={onOpen} className="title-2 text-left hover:text-accent">
          {monthOnly(m.month)}
        </button>
        <span className="text-xs text-muted">
          <span className="num">{m.days}</span> {m.days === 1 ? "day" : "days"} with records
        </span>
      </div>
      {m.written ? (
        <>
          <p className="line-clamp-4 break-words text-sm leading-relaxed text-ink/90">{m.opening}</p>
          {m.highlights.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted">
              {m.highlights.map((h) => (
                <li key={h} className="break-words">
                  {h}
                </li>
              ))}
            </ul>
          )}
          <div className="mt-auto">
            <ActionButton icon={Library} label="Read the month" tone="neutral" onClick={onOpen} />
          </div>
        </>
      ) : (
        <>
          <p className="text-sm text-muted">Not written yet.</p>
          <div className="mt-auto flex flex-wrap gap-2">
            <WriteButton month={m.month} writing={writing} onWrite={onWrite} />
            <ActionButton icon={CalendarDays} label="See its days" tone="neutral" onClick={onOpen} />
          </div>
        </>
      )}
    </article>
  );
}

/** One day: the journal's brief where there is one, whom you wrote to, and the rest by part. */
function DayCard({ d, focused }: { d: LifeDay; focused: boolean }) {
  const sources = Object.entries(d.sources);
  return (
    <article id={`day-${d.date}`} className={cn("card scroll-mt-4 space-y-3 p-4 sm:p-5", focused && "card-priority")}>
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="title-3">{longDay(d.date)}</h3>
        <span className="text-xs text-muted">
          <span className="num">{d.records}</span> {d.records === 1 ? "record" : "records"}
        </span>
      </div>
      {d.journal?.brief && <p className="break-words text-sm leading-relaxed text-ink/90">{d.journal.brief}</p>}
      {d.journal && d.journal.next_up.length > 0 && (
        <p className="break-words text-xs text-muted">
          <span className="eyebrow mr-1.5">Next up</span>
          {d.journal.next_up.join(" · ")}
        </p>
      )}
      {d.wrote.length > 0 && (
        <div>
          <p className="eyebrow mb-1">Wrote to</p>
          <ul className="space-y-1 text-sm">
            {d.wrote.map((w) => (
              <li key={`${w.channel}-${w.to}`} className="break-words">
                <span className="text-ink">{w.to}</span>
                <span className="text-muted">
                  {" "}
                  · {w.channel} · <span className="num">{w.count}</span>
                </span>
                {w.said && <span className="text-ink/75"> “{w.said}”</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {PARTS.map((p) =>
        d[p.key].length > 0 ? (
          <div key={p.key}>
            <p className="eyebrow mb-1">{p.label}</p>
            <ul className="space-y-1 text-sm text-ink/90">
              {d[p.key].map((line, i) => (
                <li key={`${p.key}-${i}`} className="break-words">
                  {line}
                </li>
              ))}
            </ul>
          </div>
        ) : null,
      )}
      {sources.length > 0 && <p className="text-xs text-muted">{sources.map(([s, n]) => `${s} ${n}`).join(" · ")}</p>}
    </article>
  );
}

interface MonthViewProps {
  data: LifeResponse;
  month: string;
  focus: string | null;
  writing: string | null;
  onBack: () => void;
  onWrite: (month: string) => void;
}

/** A month opened: its whole story and highlights, then each of its days. */
function MonthView({ data, month, focus, writing, onBack, onWrite }: MonthViewProps) {
  const open = data.open?.month === month ? data.open : null;
  const story = open?.story ?? null;
  return (
    <article className={cn("space-y-8 transition-opacity", !open && "opacity-50")} aria-busy={!open}>
      <header className="space-y-4">
        <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
          <ArrowLeft size={14} /> All of {month.slice(0, 4)}
        </button>
        <h2 className="title-1">{monthName(month)}</h2>
        {story ? (
          <div className="space-y-4">
            {story.story.split(/\n\s*\n/).map((p, i) => (
              <p key={i} className="break-words font-display text-lg leading-relaxed text-ink">
                {p}
              </p>
            ))}
          </div>
        ) : (
          <p className="text-sm leading-relaxed text-muted">
            Not written yet. Its story is a few paragraphs on what happened, what you worked on, who you were with and how you seemed,
            from the observers&apos; notes about you that month and the days below. The night writes the months with no story, newest
            first, four a night.
          </p>
        )}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-muted">
          {story?.generated && (
            <span title={formatDateTime(story.generated)}>
              Written <span className="num">{timeAgo(story.generated, data.now)}</span>
            </span>
          )}
          <WriteButton month={month} writing={writing} again={!!story} onWrite={onWrite} />
        </div>
        {story && story.highlights.length > 0 && (
          <div className="card p-4">
            <p className="eyebrow mb-2">Highlights</p>
            <ul className="list-disc space-y-1 pl-5 text-sm text-ink">
              {story.highlights.map((h) => (
                <li key={h} className="break-words">
                  {h}
                </li>
              ))}
            </ul>
          </div>
        )}
      </header>

      <section aria-label="Days" className="space-y-4">
        <div>
          <h2 className="smallcaps text-accent">Days</h2>
          <p className="text-xs text-muted">
            What the vault holds from each day: whom you wrote to, your calendar, what you wrote down, your activity and health records, by
            title, and the journal where it wrote the day. Nothing here is anyone else&apos;s words but their names.
          </p>
        </div>
        {open && open.days.length === 0 && <p className="text-sm text-muted">No day this month left a record.</p>}
        {open?.days.map((d) => <DayCard key={d.date} d={d} focused={d.date === focus} />)}
      </section>
    </article>
  );
}

/**
 * Your life by month and day, years back: a story of each month, written from the observers' notes
 * about you and its days, and each day's digest of whom you wrote to, your calendar, what you wrote
 * down, your activity and your health records. The night writes the month that just ended and fills
 * in older ones, newest first; "Write this month" writes one now.
 */
export function Life() {
  const [month, setMonth] = useState<string | null>(null);
  const [year, setYear] = useState<string | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const { data, error, write, clearError } = useLife(month);

  // Bring a day picked from the date box into view once its month is shown.
  const focusShown = focus !== null && data?.open?.days.some((d) => d.date === focus) === true;
  useEffect(() => {
    if (!focus || !focusShown) return;
    const timer = window.setTimeout(
      () => document.getElementById(`day-${focus}`)?.scrollIntoView({ behavior: "smooth", block: "start" }),
      60,
    );
    return () => window.clearTimeout(timer);
  }, [focus, focusShown]);

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load your life: ${error}`} /> : <ProseSkeleton label="Loading your life" />;
  }
  if (!data.vault.exists) return <NoVault path={data.vault.path} />;

  const banners = (
    <>
      {error && <ErrorBanner message={error} onDismiss={clearError} />}
      {data.error && <ErrorBanner message={data.error} />}
    </>
  );

  if (data.months.length === 0) {
    return (
      <div className="p-4 sm:p-6">
        {banners}
        <EmptyState icon={Library} title="Nothing to tell yet" command="proxenos index">
          The Life view tells your story by month and day, years back, from everything in the vault&apos;s memory: whom you wrote to,
          your calendar, notes, activity and health records. Bring in a source on Connect and index it, and each night a month is
          written, newest first.
        </EmptyState>
      </div>
    );
  }

  const years = [...new Set(data.months.map((m) => m.month.slice(0, 4)))];
  const shownYear = month?.slice(0, 4) ?? (year && years.includes(year) ? year : years[0]);
  const writing = data.job?.state === "running" ? data.job.month : null;
  const oldest = data.months[data.months.length - 1].month;

  const open = (m: string, day: string | null = null) => {
    setMonth(m);
    setYear(m.slice(0, 4));
    setFocus(day);
    if (!day) window.scrollTo({ top: 0 });
  };

  return (
    <div className="pb-24 md:pb-20">
      {banners}

      <div className="px-4 sm:px-6 py-3 border-b border-line flex flex-wrap items-center justify-between gap-x-4 gap-y-2 text-sm text-muted">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <label className="inline-flex items-center gap-2">
            <span>Go to</span>
            <select
              value={month ?? ""}
              onChange={(e) => (e.target.value ? open(e.target.value) : setMonth(null))}
              className="num bg-surface border border-line-strong rounded-full px-3 py-1 text-sm text-ink hover:border-accent/40"
            >
              <option value="">A month…</option>
              {years.map((y) => (
                <optgroup key={y} label={y}>
                  {data.months
                    .filter((m) => m.month.startsWith(y))
                    .map((m) => (
                      <option key={m.month} value={m.month}>
                        {monthName(m.month)}
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
          </label>
          <label className="inline-flex items-center gap-2">
            <span>or a day</span>
            <input
              type="date"
              min={`${oldest}-01`}
              max={data.today}
              value={focus ?? ""}
              onChange={(e) => /^\d{4}-\d{2}-\d{2}$/.test(e.target.value) && open(e.target.value.slice(0, 7), e.target.value)}
              className="num bg-surface border border-line-strong rounded-full px-3 py-1 text-sm text-ink hover:border-accent/40"
            />
          </label>
        </div>
        <span>
          {writing ? (
            <>Writing {monthName(writing)}…</>
          ) : data.left > 0 ? (
            <>
              <span className="num">{data.left}</span> {data.left === 1 ? "month" : "months"} to write; the night writes four a night, newest
              first
            </>
          ) : (
            "The night writes each month as it ends"
          )}
        </span>
      </div>

      <div className="px-4 sm:px-6 pt-4 overflow-x-auto [&>div]:w-max">
        <Segmented
          label="Year"
          tabs={years.map((y) => ({ id: y, label: y }))}
          value={shownYear}
          onChange={(y) => {
            setYear(y);
            setMonth(null);
            setFocus(null);
          }}
        />
      </div>

      <div className="p-4 sm:p-6 max-w-3xl">
        {month ? (
          <MonthView
            data={data}
            month={month}
            focus={focus}
            writing={writing}
            onBack={() => {
              setMonth(null);
              setFocus(null);
            }}
            onWrite={write}
          />
        ) : (
          <div className="grid items-start gap-4 sm:grid-cols-2">
            {data.months
              .filter((m) => m.month.startsWith(shownYear))
              .map((m) => (
                <MonthCard key={m.month} m={m} writing={writing} onOpen={() => open(m.month)} onWrite={write} />
              ))}
          </div>
        )}
      </div>
    </div>
  );
}
