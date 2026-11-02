"use client";

import { useEffect, useState, type ReactNode } from "react";
import { ArrowLeft, CalendarDays, Library, MessagesSquare, PenLine, RefreshCw } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { EmptyState, ErrorBanner, NoVault } from "@/components/EmptyState";
import { Segmented } from "@/components/layout/Segmented";
import { ProseSkeleton } from "@/components/Skeleton";
import { monthName, useLife } from "@/lib/client";
import { formatDateTime, longDay, timeAgo } from "@/lib/format";
import type { LifeDay, LifeEntry, LifeMonth, LifeResponse, ThinkStart } from "@/lib/types";
import { cn } from "@/lib/utils";

type Listed = "events" | "notes" | "health" | "activity" | "other";

const PARTS: { key: Listed; label: string }[] = [
  { key: "events", label: "Calendar" },
  { key: "notes", label: "Wrote down" },
  { key: "health", label: "Health records" },
  { key: "activity", label: "Activity" },
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

/** A month in a year's list: its summary's opening and highlights, or "Not written yet". */
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

/** A line of the records: its label, then what it holds as running text, quiet. */
function RecordLine({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-x-4 gap-y-0.5 sm:grid-cols-[7rem_1fr]">
      <dt className="text-xs text-muted sm:pt-px">{label}</dt>
      <dd className="break-words text-ink/70">{children}</dd>
    </div>
  );
}

/** One day: its diary entry where the month has one, then what the records hold from it, quietly, by part. */
function DayCard({ d, entry, focused, onThink }: { d: LifeDay; entry: string | null; focused: boolean; onThink?: () => void }) {
  const sources = Object.entries(d.sources);
  return (
    <article id={`day-${d.date}`} className={cn("card scroll-mt-4 space-y-3 p-4 sm:p-5", focused && "card-priority")}>
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="title-3">{longDay(d.date)}</h3>
        <span className="text-xs text-muted">
          <span className="num">{d.records}</span> {d.records === 1 ? "record" : "records"}
        </span>
      </div>
      {entry && <p className="break-words font-display text-base leading-relaxed text-ink">{entry}</p>}
      <div className={cn("space-y-2", entry && "border-t border-line pt-3")}>
        <p className="text-xs text-muted">From the records</p>
        <dl className="space-y-1.5 text-sm leading-relaxed">
          {d.journal?.brief && <RecordLine label="Journal">{d.journal.brief}</RecordLine>}
          {d.wrote.length > 0 && (
            <RecordLine label="Wrote to">
              {d.wrote.map((w, i) => (
                <span key={`${w.channel}-${w.to}`}>
                  {i > 0 && <span className="text-muted"> · </span>}
                  {w.to}
                  <span className="text-muted">
                    {" "}
                    ({w.channel}, <span className="num">{w.count}</span>)
                  </span>
                  {w.said && <span className="italic"> “{w.said}”</span>}
                </span>
              ))}
            </RecordLine>
          )}
          {PARTS.map((p) =>
            d[p.key].length > 0 ? (
              <RecordLine key={p.key} label={p.label}>
                {d[p.key].join(" · ")}
              </RecordLine>
            ) : null,
          )}
        </dl>
        {sources.length > 0 && <p className="text-xs text-muted">{sources.map(([s, n]) => `${s} ${n}`).join(" · ")}</p>}
      </div>
      {onThink && <ActionButton icon={MessagesSquare} label="Think about this day" tone="neutral" onClick={onThink} />}
    </article>
  );
}

/** A month's diary: each entry under its day, which leads to that day's records below. */
function Diary({ entries }: { entries: LifeEntry[] }) {
  return (
    <section aria-label="Diary" className="space-y-6">
      {entries.map((e) => (
        <div key={e.day} className="space-y-1.5">
          <a href={`#day-${e.day}`} className="smallcaps hover:text-accent">
            {longDay(e.day)}
          </a>
          <p className="break-words font-display text-lg leading-relaxed text-ink">{e.text}</p>
        </div>
      ))}
    </section>
  );
}

interface MonthViewProps {
  data: LifeResponse;
  month: string;
  focus: string | null;
  writing: string | null;
  onBack: () => void;
  onWrite: (month: string) => void;
  onThink?: (start: ThinkStart) => void;
}

/** A month opened: its summary and diary, then each of its days. */
function MonthView({ data, month, focus, writing, onBack, onWrite, onThink }: MonthViewProps) {
  const open = data.open?.month === month ? data.open : null;
  const story = open?.story ?? null;
  const entries = story?.entries ?? null;
  const entryOn = new Map((entries ?? []).map((e) => [e.day, e.text]));
  return (
    <article className={cn("space-y-8 transition-opacity", !open && "opacity-50")} aria-busy={!open}>
      <header className="space-y-4">
        <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
          <ArrowLeft size={14} /> All of {month.slice(0, 4)}
        </button>
        <h2 className="title-1">{monthName(month)}</h2>
        {story ? (
          <div className="space-y-4">
            {story.summary.split(/\n\s*\n/).map((p, i) => (
              <p key={i} className="break-words font-display text-lg leading-relaxed text-ink">
                {p}
              </p>
            ))}
          </div>
        ) : (
          <p className="text-sm leading-relaxed text-muted">
            Not written yet. Its diary is a few sentences on the month and an entry, in your own voice, for each day that mattered: from
            your care and health records, what you told Proxenos, the observers&apos; notes about you that month and the days below. The
            night writes the months with no diary, newest first, four a night.
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
        {story && !entries && (
          <>
            <p className="text-xs text-muted">Written before months had diary entries: the night writes it again as a diary.</p>
            {story.highlights.length > 0 && (
              <ul className="list-disc space-y-1 pl-5 text-sm text-ink/90">
                {story.highlights.map((h) => (
                  <li key={h} className="break-words">
                    {h}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </header>

      {entries && entries.length > 0 && <Diary entries={entries} />}

      <section aria-label="Days" className="space-y-4">
        <div>
          <h2 className="smallcaps text-accent">Days</h2>
          <p className="text-xs text-muted">
            Each day&apos;s diary entry, where the month has one, then what the vault holds from it: whom you wrote to, your calendar, what
            you wrote down, your health records and activity, by title, and the journal where it wrote the day. Nothing here is anyone
            else&apos;s words but their names.
          </p>
        </div>
        {open && open.days.length === 0 && <p className="text-sm text-muted">No day this month left a record.</p>}
        {open?.days.map((d) => (
          <DayCard
            key={d.date}
            d={d}
            entry={entryOn.get(d.date) ?? null}
            focused={d.date === focus}
            onThink={
              onThink &&
              (() =>
                onThink({
                  kind: "day",
                  id: d.date,
                  label: `Day: ${longDay(d.date)}`,
                  text: `Help me think about ${longDay(d.date)}.`,
                }))
            }
          />
        ))}
      </section>
    </article>
  );
}

/**
 * Your life by month and day, years back: a diary of each month, in your own voice, written from your
 * care, what you told Proxenos, the observers' notes about you and its days, and under each day's
 * entry what the records hold: whom you wrote to, your calendar, what you wrote down, your health
 * records and your activity. The night writes the month that just ended and fills in older ones,
 * newest first; "Write this month" writes one now.
 */
export function Life({ onThink }: { onThink?: (start: ThinkStart) => void } = {}) {
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
            onThink={onThink}
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
