"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { ArrowLeft, CalendarDays, Check, CircleSlash, Library, MessagesSquare, PenLine, Pencil, RefreshCw, X } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { EmptyState, ErrorBanner, NoVault } from "@/components/EmptyState";
import { Segmented } from "@/components/layout/Segmented";
import { Listen } from "@/components/reading/Listen";
import { ProseSkeleton } from "@/components/Skeleton";
import { monthName, useLife } from "@/lib/client";
import { formatDateTime, longDay, timeAgo, wordsKey } from "@/lib/format";
import { scrollBehavior } from "@/lib/reading";
import type { LifeCorrection, LifeDay, LifeEntry, LifeMonth, LifeResponse, LifeStory, ThinkStart } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Mark an item of the month shown not true, with what's true in the user's words, or (`undo`) take that back. */
type MarkFn = (item: string, text: string, correction: string, undo?: boolean) => Promise<boolean>;

/** The month's marks of "not true", found by the item and what it said. */
function marksOf(corrections: LifeCorrection[]): (item: string, text: string) => LifeCorrection | null {
  const by = new Map(corrections.map((c) => [`${c.item}\n${wordsKey(c.text)}`, c]));
  return (item, text) => by.get(`${item}\n${wordsKey(text)}`) ?? null;
}

const CORRECTION_CHARS = 1000; // as the API takes one
const FIELD = "w-full rounded-xl border border-line-strong bg-bg p-3 text-ink leading-relaxed resize-y font-sans";

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
  /** The abstract and essay shown are the user's own: writing it again asks first. */
  edited?: boolean;
  onWrite: (month: string, again?: boolean) => void;
}

function WriteButton({ month, writing, again = false, edited = false, onWrite }: WriteProps) {
  const [sure, setSure] = useState(false);
  const mine = writing === month;
  if (sure && !mine) {
    return (
      <span role="group" aria-label="Write this month again?" className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-ink">Write it again from your text, in place of it?</span>
        <ActionButton
          icon={RefreshCw}
          label="Write again"
          name="Write again, from your text"
          tone="accent"
          active
          disabled={writing !== null}
          onClick={() => {
            setSure(false);
            onWrite(month, true);
          }}
        />
        <ActionButton icon={X} label="Not yet" tone="neutral" onClick={() => setSure(false)} />
      </span>
    );
  }
  return (
    <ActionButton
      icon={again ? RefreshCw : PenLine}
      label={mine ? "Writing… a few minutes" : again ? "Write again" : "Write this month"}
      tone="accent"
      active={mine || !again}
      disabled={writing !== null}
      onClick={() => (edited ? setSure(true) : onWrite(month))}
    />
  );
}

/** A month in a year's list: its abstract and highlights, or "Not written yet". */
function MonthCard({
  m,
  writing,
  onOpen,
  onWrite,
}: {
  m: LifeMonth;
  writing: string | null;
  onOpen: () => void;
  onWrite: (month: string) => void;
}) {
  return (
    <article className="card card-hover flex flex-col gap-3 p-4 sm:p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <button type="button" onClick={onOpen} className="title-2 text-left hover:text-accent">
          {monthOnly(m.month)}
        </button>
        <span className="text-xs text-muted">
          <span className="num">{m.days}</span> {m.days === 1 ? "day" : "days"} with records
        </span>
      </div>
      {m.written ? (
        <>
          <p className="break-words text-sm leading-relaxed text-ink/90">{m.opening}</p>
          {m.edited && <p className="text-xs text-muted">In your own words</p>}
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
            <ActionButton icon={Library} label="Read the month" name={`Read ${monthName(m.month)}`} tone="neutral" onClick={onOpen} />
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

interface MarkableProps {
  item: string;
  /** What the item says, as the diary keeps it: what a mark goes by. */
  text: string;
  /** What it is, for a screen reader: "paragraph 2 of the essay". */
  what: string;
  mark: LifeCorrection | null;
  onMark: MarkFn;
  children: ReactNode;
}

/**
 * Something in a month's diary the user can say isn't true: its text, then a quiet "Not true", which asks
 * what is true, in their words, if they'd say. Marked, it's struck out with what they said, and Undo.
 */
function Markable({ item, text, what, mark, onMark, children }: MarkableProps) {
  const [asking, setAsking] = useState(false);
  const [said, setSaid] = useState("");
  const [saving, setSaving] = useState(false);
  // Marked or taken back, the control that takes its place gets the focus, so the keyboard isn't lost: once,
  // as it's struck out (or back) on the page, not again when the saved marks come back.
  const acted = useRef(false);
  const field = useRef<HTMLTextAreaElement>(null);
  const next = useRef<HTMLButtonElement>(null);
  const id = useId();
  const marked = mark !== null;
  useEffect(() => {
    if (!acted.current) return;
    acted.current = false;
    next.current?.focus();
  }, [marked]);

  const submit = async () => {
    if (saving) return;
    setSaving(true);
    acted.current = true;
    const ok = await onMark(item, text, said.trim());
    setSaving(false);
    if (ok) {
      setAsking(false);
      setSaid("");
    }
  };

  if (mark) {
    return (
      <div className="space-y-1">
        <div className="break-words text-muted line-through decoration-1">{children}</div>
        <p className="break-words text-sm leading-relaxed text-ink/90">
          <span className="font-medium text-bad-ink">Not true.</span>
          {mark.correction && <> What&apos;s true: &ldquo;{mark.correction}&rdquo;</>}{" "}
          <button
            ref={next}
            type="button"
            onClick={() => {
              acted.current = true;
              void onMark(item, text, "", true);
            }}
            aria-label={`Undo not true: ${what}`}
            className="text-accent underline-offset-4 hover:underline"
          >
            Undo
          </button>
        </p>
      </div>
    );
  }

  return (
    <div>
      {children}
      {asking ? (
        <div role="group" aria-label={`Not true: ${what}`} className="mt-2 space-y-2 rounded-xl border border-line-strong bg-surface-2 p-3">
          <label htmlFor={id} className="block text-sm text-ink">
            What&apos;s true, in your words <span className="text-muted">(if you&apos;d say)</span>
          </label>
          <textarea
            id={id}
            ref={field}
            value={said}
            maxLength={CORRECTION_CHARS}
            onChange={(e) => setSaid(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setAsking(false);
              else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                void submit();
              }
            }}
            rows={2}
            spellCheck
            className={cn(FIELD, "text-sm")}
          />
          <div className="flex flex-wrap items-center gap-2">
            <ActionButton
              icon={CircleSlash}
              label={saving ? "Saving" : "Mark not true"}
              name={`Mark not true: ${what}`}
              tone="bad"
              active
              disabled={saving}
              onClick={() => void submit()}
            />
            <ActionButton icon={X} label="Cancel" tone="neutral" onClick={() => setAsking(false)} />
            <span className="text-xs text-muted">The next time the month is written, this leads it, and it&apos;s never written again.</span>
          </div>
        </div>
      ) : (
        <button
          ref={next}
          type="button"
          onClick={() => {
            setAsking(true);
            window.setTimeout(() => field.current?.focus(), 0); // once it's there
          }}
          aria-label={`Not true: ${what}`}
          className="mt-1 text-xs text-muted underline-offset-4 hover:text-bad-ink hover:underline"
        >
          Not true
        </button>
      )}
    </div>
  );
}

/** The month's abstract and essay as the user edits them: theirs once saved, which the night never writes over. */
function EssayEditor({ story, onSave, onCancel }: { story: LifeStory; onSave: (summary: string, essay: string) => Promise<boolean>; onCancel: () => void }) {
  const [summary, setSummary] = useState(story.summary);
  const [essay, setEssay] = useState(story.essay);
  const [saving, setSaving] = useState(false);
  const first = useRef<HTMLTextAreaElement>(null);
  const ids = useId();
  useEffect(() => first.current?.focus(), []);

  const save = async () => {
    if (saving || !(summary.trim() || essay.trim())) return;
    setSaving(true);
    await onSave(summary, essay);
    setSaving(false);
  };
  const keys = (e: KeyboardEvent) => {
    if (e.key === "Escape") onCancel();
    else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void save();
    }
  };

  return (
    <section aria-label="Edit the month" className="space-y-4">
      <div className="space-y-1">
        <label htmlFor={`${ids}-abstract`} className="block text-sm font-medium text-ink">
          Abstract
        </label>
        <p id={`${ids}-abstract-hint`} className="text-xs text-muted">
          Two to four sentences, on the month&apos;s card.
        </p>
        <textarea
          id={`${ids}-abstract`}
          ref={first}
          aria-describedby={`${ids}-abstract-hint`}
          value={summary}
          maxLength={2000}
          onChange={(e) => setSummary(e.target.value)}
          onKeyDown={keys}
          rows={4}
          spellCheck
          className={cn(FIELD, "text-base")}
        />
      </div>
      <div className="space-y-1">
        <label htmlFor={`${ids}-essay`} className="block text-sm font-medium text-ink">
          Essay
        </label>
        <p id={`${ids}-essay-hint`} className="text-xs text-muted">
          A blank line between paragraphs.
        </p>
        <textarea
          id={`${ids}-essay`}
          aria-describedby={`${ids}-essay-hint`}
          value={essay}
          maxLength={20000}
          onChange={(e) => setEssay(e.target.value)}
          onKeyDown={keys}
          rows={Math.min(30, Math.max(12, essay.split("\n").length + 2))}
          spellCheck
          className={cn(FIELD, "font-display text-lg")}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <ActionButton
          icon={Check}
          label={saving ? "Saving" : "Save"}
          tone="accent"
          active
          disabled={saving || !(summary.trim() || essay.trim())}
          onClick={() => void save()}
        />
        <ActionButton icon={X} label="Cancel" tone="neutral" onClick={onCancel} />
        <span className="text-xs text-muted sm:ml-auto">
          Saved, it&apos;s yours: the night never writes over it, and Write again asks first, then writes from it. ⌘↵ saves, Esc
          cancels.
        </span>
      </div>
    </section>
  );
}

/** A month's diary: each entry under its day, which leads to that day's records below. */
function Diary({ entries, markOf, onMark }: { entries: LifeEntry[]; markOf: ReturnType<typeof marksOf>; onMark: MarkFn }) {
  return (
    <section aria-labelledby="life-diary" className="space-y-6">
      <h3 id="life-diary" className="smallcaps text-accent">
        Day by day
      </h3>
      {entries.map((e) => (
        <div key={e.day} className="space-y-1.5">
          <a href={`#day-${e.day}`} className="smallcaps hover:text-accent">
            {longDay(e.day)}
          </a>
          <Markable
            item={`entry:${e.day}`}
            text={e.text}
            what={`the entry for ${longDay(e.day)}`}
            mark={markOf(`entry:${e.day}`, e.text)}
            onMark={onMark}
          >
            <p className="break-words font-display text-lg leading-relaxed text-ink">{e.text}</p>
          </Markable>
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
  onWrite: (month: string, again?: boolean) => void;
  onSave: (month: string, summary: string, essay: string) => Promise<boolean>;
  onMark: (month: string, item: string, text: string, correction: string, undo?: boolean) => Promise<boolean>;
  onThink?: (start: ThinkStart) => void;
}

/** A month opened: its abstract and essay, its highlights and diary, then each of its days. */
function MonthView({ data, month, focus, writing, onBack, onWrite, onSave, onMark, onThink }: MonthViewProps) {
  const [editing, setEditing] = useState(false);
  const open = data.open?.month === month ? data.open : null;
  const story = open?.story ?? null;
  const entries = story?.entries ?? null;
  const markOf = marksOf(open?.corrections ?? []);
  const mark: MarkFn = (item, text, correction, undo) => onMark(month, item, text, correction, undo);
  const paragraphs = story?.essay ? story.essay.split(/\n\s*\n/) : [];
  // A day's entry shows under it too, unless it was marked not true.
  const entryOn = new Map((entries ?? []).filter((e) => !markOf(`entry:${e.day}`, e.text)).map((e) => [e.day, e.text]));
  const spoken = [story?.summary ?? "", ...paragraphs.filter((p) => !markOf("essay", p))].filter(Boolean).join("\n\n");
  return (
    <article className={cn("space-y-8 transition-opacity", !open && "opacity-50")} aria-busy={!open}>
      <header className="space-y-4">
        <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
          <ArrowLeft size={14} aria-hidden="true" /> All of {month.slice(0, 4)}
        </button>
        <h2 className="title-1">{monthName(month)}</h2>
        {story && !editing && story.summary && (
          <div className="space-y-4">
            {story.summary.split(/\n\s*\n/).map((p, i) => (
              <p key={i} className="break-words text-lg leading-relaxed text-ink/90">
                {p}
              </p>
            ))}
          </div>
        )}
        {!story && (
          <p className="text-sm leading-relaxed text-muted">
            Not written yet. Its diary is a short abstract, an essay of the month and an entry, in your own voice, for each day that
            mattered: from what you told Proxenos that month first, then your care and health records, the observers&apos; notes about
            you that month and the days below. The night writes the months with no diary, newest first, four a night.
          </p>
        )}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-muted">
          {story?.edited ? (
            <span title={formatDateTime(story.edited)}>
              In your own words, saved <span className="num">{timeAgo(story.edited, data.now)}</span>
            </span>
          ) : (
            story?.generated && (
              <span title={formatDateTime(story.generated)}>
                Written <span className="num">{timeAgo(story.generated, data.now)}</span>
              </span>
            )
          )}
          {story && !editing && (
            <ActionButton icon={Pencil} label="Edit" name={`Edit ${monthName(month)}`} tone="neutral" onClick={() => setEditing(true)} />
          )}
          {!editing && spoken && <Listen id={`life:${month}`} text={spoken} what={monthName(month)} />}
          <WriteButton month={month} writing={writing} again={!!story} edited={!!story?.edited} onWrite={onWrite} />
        </div>
      </header>

      {editing && story ? (
        <EssayEditor
          story={story}
          onCancel={() => setEditing(false)}
          onSave={async (summary, essay) => {
            const ok = await onSave(month, summary, essay);
            if (ok) setEditing(false);
            return ok;
          }}
        />
      ) : paragraphs.length > 0 ? (
        <section aria-label="Essay" className="space-y-5">
          {paragraphs.map((p, i) => (
            <Markable
              key={`${i}-${p.slice(0, 24)}`}
              item="essay"
              text={p}
              what={`paragraph ${i + 1} of the essay`}
              mark={markOf("essay", p)}
              onMark={mark}
            >
              <p className="break-words font-display text-lg leading-relaxed text-ink">{p}</p>
            </Markable>
          ))}
        </section>
      ) : (
        story &&
        entries && (
          <p className="text-xs text-muted">
            Written before months had an essay: the night writes it again with one, or Write again does now.
          </p>
        )
      )}
      {story && !entries && (
        <p className="text-xs text-muted">Written before months had diary entries: the night writes it again as a diary.</p>
      )}

      {story && story.highlights.length > 0 && (
        <section aria-labelledby="life-highlights" className="space-y-3">
          <h3 id="life-highlights" className="smallcaps text-accent">
            Highlights
          </h3>
          <ul className="space-y-2">
            {story.highlights.map((h) => (
              <li key={h} className="border-l-2 border-line-strong pl-3">
                <Markable item="highlight" text={h} what={`the highlight ${h}`} mark={markOf("highlight", h)} onMark={mark}>
                  <span className="break-words text-ink/90">{h}</span>
                </Markable>
              </li>
            ))}
          </ul>
        </section>
      )}

      {entries && entries.length > 0 && <Diary entries={entries} markOf={markOf} onMark={mark} />}

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
 * Your life by month and day, years back: a diary of each month, in your own voice (an abstract on its
 * card, and opened, an essay, its highlights and an entry for each day that mattered), written from
 * what you told Proxenos that month first, your care, the observers' notes about you and its days, and
 * under each day's entry what the records hold: whom you wrote to, your calendar, what you wrote down,
 * your health records and your activity. The abstract and essay are yours to edit, and anything in it
 * yours to mark not true, which the next write of the month goes by. The night writes the month that
 * just ended and fills in older ones, newest first; "Write this month" writes one now.
 */
export function Life({ onThink }: { onThink?: (start: ThinkStart) => void } = {}) {
  const [month, setMonth] = useState<string | null>(null);
  const [year, setYear] = useState<string | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const { data, error, write, saveEdit, mark, clearError } = useLife(month);

  // Bring a day picked from the date box into view once its month is shown.
  const focusShown = focus !== null && data?.open?.days.some((d) => d.date === focus) === true;
  useEffect(() => {
    if (!focus || !focusShown) return;
    const timer = window.setTimeout(
      () => document.getElementById(`day-${focus}`)?.scrollIntoView({ behavior: scrollBehavior(), block: "start" }),
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
          your calendar, notes, activity and health records. Connect a source, then press Make it now to index it. Each night after
          that, a month is written, newest first.
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
            key={month}
            data={data}
            month={month}
            focus={focus}
            writing={writing}
            onBack={() => {
              setMonth(null);
              setFocus(null);
            }}
            onWrite={write}
            onSave={saveEdit}
            onMark={mark}
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
