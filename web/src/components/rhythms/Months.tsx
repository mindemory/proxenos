"use client";

import { useState, type ReactNode } from "react";
import { ChevronRight, Headphones, Library, Link2, PenLine, Smile } from "lucide-react";

import { Columns } from "@/components/charts/Columns";
import { Diverging } from "@/components/charts/Diverging";
import { monthName } from "@/lib/client";
import { longDay } from "@/lib/format";
import type { RhythmsMonthCard, RhythmsMonthDay, RhythmsMonths, RhythmsShare } from "@/lib/types";
import { cn } from "@/lib/utils";

const BRIGHTER = 0.25; // the mood clone's lines: a day at or past them ran brighter, or heavier
const HEAVIER = -0.05;
const CARD_ID = "rhythms-month-card";
const OPEN_DAYS = 5; // days with a mood the month opened at first needs

function amount(v: number): string {
  if (v === 0) return "0";
  return v < 10 ? v.toFixed(1) : Math.round(v).toLocaleString("en-US");
}

function count(v: number): string {
  return v.toLocaleString("en-US");
}

function percent(v: number): string {
  return `${Math.round(v * 100)}%`;
}

function plural(n: number, word: string): string {
  return `${count(n)} ${n === 1 ? word : `${word}s`}`;
}

/** -0.42 as "−0.42", with a true minus. */
function signed(v: number): string {
  return v.toFixed(2).replace("-", "−");
}

/** How a day's or a week's writing ran, in a word. */
function tone(v: number | null): string {
  if (v === null) return "too little writing to read";
  return v >= BRIGHTER ? "brighter" : v <= HEAVIER ? "heavier" : "mixed";
}

/** "Mar 9", from a YYYY-MM-DD. */
function day(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** "20% more than your usual month", or by this point in one for a month still going. */
function besideUsual(c: RhythmsMonthCard): string | null {
  const change = c.writing.beside_usual;
  if (change === null) return null;
  const by = c.writing.usual_by_now !== null ? " by this point" : "";
  if (Math.abs(change) < 0.1) return `About as much as your usual month${by}`;
  return `${percent(Math.abs(change))} ${change > 0 ? "more" : "less"} than your usual month${by}`;
}

/** A month in the list: its name, its top moods, its hours and words. */
function MonthButton({ c, open, onOpen }: { c: RhythmsMonthCard; open: boolean; onOpen: () => void }) {
  const [name, year] = monthName(c.month).split(" ");
  const moods = c.mood.top.slice(0, 2).map((t) => t.name);
  const said = moods.length ? moods.join(", ") : c.mood.days ? `${c.mood.tone.brighter} brighter days` : "no mood to read";
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-pressed={open}
      aria-controls={CARD_ID}
      className={cn(
        "flex w-44 flex-col gap-1 rounded-lg border px-3 py-2.5 text-left transition-colors lg:w-full",
        open ? "border-line-strong bg-surface-2" : "border-line hover:border-line-strong hover:bg-surface-2",
      )}
    >
      <span className="flex items-baseline justify-between gap-2">
        <span className="title-3">{name}</span>
        <span className="num whitespace-nowrap text-xs text-muted">
          {year}
          {!c.complete && " · so far"}
        </span>
      </span>
      <span className="truncate text-sm text-ink/90">{said}</span>
      <span className="num text-xs text-muted">
        {amount(c.music.music_hours)} h · {count(c.writing.words)} words
      </span>
    </button>
  );
}

/** A part of the card: its heading, then what it holds. */
function Part({ icon: Icon, title, children }: { icon: typeof Smile; title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="min-w-0 space-y-2.5">
      <h4 className="smallcaps flex items-center gap-1.5">
        <Icon size={14} aria-hidden="true" className="text-muted" />
        {title}
      </h4>
      {children}
    </section>
  );
}

/** Labels by hours as a list: each name, a bar for its share, and the hours as text. */
function Shares({ items, label }: { items: RhythmsShare[]; label: string }) {
  if (!items.length) return null;
  return (
    <div className="space-y-1.5">
      <p className="text-xs text-muted">{label}</p>
      <ul className="space-y-1">
        {items.slice(0, 3).map((s) => (
          <li key={s.name} className="text-sm">
            <div className="flex items-baseline justify-between gap-2">
              <span className="min-w-0 break-words text-ink">{s.name}</span>
              <span className="num shrink-0 text-xs text-muted">
                {amount(s.hours)} h · {percent(s.share)}
              </span>
            </div>
            <div className="mt-0.5 h-1 rounded-full bg-surface-2" aria-hidden="true">
              <div className="h-1 rounded-full bg-accent/70" style={{ width: percent(s.share) }} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function MoodPart({ c, localModel }: { c: RhythmsMonthCard; localModel: boolean }) {
  const m = c.mood;
  if (!m.days) {
    return (
      <Part icon={Smile} title="Mood">
        <p className="text-sm text-muted">Too little of your own writing this month to read its mood.</p>
      </Part>
    );
  }
  const spread = m.variability;
  const vsUsual =
    spread.sd !== null && m.usual_sd !== null
      ? spread.sd > m.usual_sd * 1.2
        ? ", more than usual"
        : spread.sd < m.usual_sd * 0.8
          ? ", less than usual"
          : ", as usual"
      : "";
  return (
    <Part icon={Smile} title="Mood">
      {m.top.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5" aria-label="Top moods">
          {m.top.map((t) => (
            <li
              key={t.name}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-sm",
                t.bright ? "border-ok-line bg-ok-bg text-ok-ink" : "border-warn-line bg-warn-bg text-warn-ink",
              )}
            >
              {t.name}{" "}
              <span className="num text-xs">
                · {t.days} of {m.labelled_days} days
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">
          {localModel ? "No feelings named yet: the night names them." : "Feelings are named only by a model on this computer."}
        </p>
      )}
      <p className="text-sm text-ink/90">
        <span className="num">{m.tone.brighter}</span> brighter, <span className="num">{m.tone.mixed}</span> mixed and{" "}
        <span className="num">{m.tone.heavier}</span> heavier {m.days === 1 ? "day" : "days"}
        <span className="text-muted"> of {plural(m.days, "day")} with enough writing</span>
      </p>
      <dl className="space-y-1 text-sm">
        {m.arc.best && (
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-muted">Brightest week</dt>
            <dd className="text-ink">
              from {day(m.arc.best.start)}
              {m.arc.best.emotion && <span className="text-muted">, mostly {m.arc.best.emotion}</span>}
            </dd>
          </div>
        )}
        {m.arc.hardest && (
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-muted">Hardest week</dt>
            <dd className="text-ink">
              from {day(m.arc.hardest.start)}
              {m.arc.hardest.emotion && <span className="text-muted">, mostly {m.arc.hardest.emotion}</span>}
            </dd>
          </div>
        )}
        {spread.word && (
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-muted">Day to day</dt>
            <dd className="text-ink">
              {spread.word}
              <span className="text-muted">{vsUsual}</span>
            </dd>
          </div>
        )}
      </dl>
    </Part>
  );
}

function MusicPart({ c, musicbrainz }: { c: RhythmsMonthCard; musicbrainz: boolean }) {
  const h = c.music;
  if (!h.hours) {
    return (
      <Part icon={Headphones} title="Music">
        <p className="text-sm text-muted">No listening this month.</p>
      </Part>
    );
  }
  return (
    <Part icon={Headphones} title="Music">
      <p className="text-sm text-ink">
        <span className="num text-lg">{amount(h.music_hours)}</span> hours of music
        {h.spoken_hours > 0 && <span className="text-muted">, and {amount(h.spoken_hours)} of podcasts and books</span>}
      </p>
      <Shares items={h.genres} label="Genres" />
      <Shares items={h.kinds} label={musicbrainz ? "Kinds, from MusicBrainz" : "Kinds"} />
      <Shares items={h.moods} label="Moods of the music" />
      {h.top_artists.length > 0 && (
        <p className="text-sm">
          <span className="text-xs text-muted">Most played </span>
          <span className="break-words text-ink">{h.top_artists.slice(0, 3).map((a) => a.name).join(", ")}</span>
        </p>
      )}
      {h.labelled < 0.9 && (
        <p className="text-xs text-muted">
          <span className="num">{percent(h.labelled)}</span> of it has a genre or mood so far.
        </p>
      )}
    </Part>
  );
}

function WritingPart({ c }: { c: RhythmsMonthCard }) {
  const w = c.writing;
  const usual = besideUsual(c);
  return (
    <Part icon={PenLine} title="Writing">
      <p className="text-sm text-ink">
        <span className="num text-lg">{count(w.words)}</span> words{!c.complete && " so far"}
      </p>
      {usual && <p className="text-sm text-muted">{usual}.</p>}
      {(w.channels.length > 0 || w.notes.count > 0) && (
        <ul className="space-y-0.5 text-sm">
          {w.channels.map((ch) => (
            <li key={ch.name} className="flex justify-between gap-2">
              <span className="text-ink">{ch.name}</span>
              <span className="num text-muted">{count(ch.words)}</span>
            </li>
          ))}
          {w.notes.count > 0 && (
            <li className="flex justify-between gap-2">
              <span className="text-ink">Notes ({w.notes.count})</span>
              <span className="num text-muted">{count(w.notes.words)}</span>
            </li>
          )}
        </ul>
      )}
      {w.documents.count > 0 && (
        <p className="text-xs text-muted">
          You changed {plural(w.documents.count, "document")} too, <span className="num">{count(w.documents.words)}</span> words in all
          (not counted above).
        </p>
      )}
    </Part>
  );
}

/** A day as the readout and the slider say it. */
function dayLine(d: RhythmsMonthDay): string {
  const parts = [d.valence === null ? "too little writing to read" : `${tone(d.valence)} (${signed(d.valence)})`];
  if (d.emotions.length) parts.push(d.emotions.join(", "));
  return parts.join(", ");
}

/** The month's days: the mood of the writing and the music, aligned, with the day picked said in words. */
function Days({ c }: { c: RhythmsMonthCard }) {
  const [hover, setHover] = useState<number | null>(null);
  const [pick, setPick] = useState<{ month: string; i: number } | null>(null);
  const days = c.days;
  if (!days.length) return null;
  const held = days.findLastIndex((d) => d.valence !== null || d.music_hours > 0);
  const picked = pick && pick.month === c.month && pick.i < days.length ? pick.i : held >= 0 ? held : days.length - 1;
  const shown = hover ?? picked;
  const d = days[shown];
  const name = (i: number) => longDay(days[i].day);
  const ticks = days.map((x, i) => ({ i, text: day(x.day) })).filter((t) => t.i % 7 === 0);
  return (
    <section aria-label="Day by day" className="space-y-3 border-t border-line pt-4">
      <div className="space-y-1" aria-live="polite">
        <h4 className="title-3">{longDay(d.day)}</h4>
        <p className="text-sm text-ink/90">
          Your writing: <span className="text-ink">{dayLine(d)}</span>
          {d.words > 0 && <span className="text-muted"> · {plural(d.words, "word")}</span>}
        </p>
        <p className="text-sm text-ink/90">
          Music: <span className="num text-ink">{amount(d.music_hours)} h</span>
          {d.upbeat !== null && <span className="text-muted"> · {percent(d.upbeat)} upbeat</span>}
          {d.melancholic !== null && <span className="text-muted"> · {percent(d.melancholic)} melancholic</span>}
        </p>
      </div>
      <div className="space-y-1.5">
        <span className="smallcaps">Mood of your writing</span>
        <div className="mr-14">
          <Diverging
            values={days.map((x) => x.valence)}
            label="Mood of your writing, by day: up is brighter, down is heavier"
            picked={shown}
            onHover={setHover}
            onPick={(i) => setPick({ month: c.month, i })}
            format={(v) => (v === null ? "too little writing to read" : `${tone(v)} (${signed(v)})`)}
            name={name}
          />
        </div>
      </div>
      <div className="space-y-1.5">
        <span className="smallcaps">Hours of music</span>
        <Columns
          values={days.map((x) => x.music_hours)}
          label="Hours of music, by day"
          picked={shown}
          onHover={setHover}
          onPick={(i) => setPick({ month: c.month, i })}
          format={(v) => `${amount(v)} h`}
          name={name}
        />
      </div>
      <div className="relative mr-14 h-4 text-[0.6875rem] text-faint" aria-hidden="true">
        {ticks.map((t) => (
          <span
            key={t.i}
            className="num absolute top-0 whitespace-nowrap"
            style={{ left: `${((t.i + 0.5) / days.length) * 100}%`, transform: t.i === 0 ? "none" : "translateX(-50%)" }}
          >
            {t.text}
          </span>
        ))}
      </div>
      <p className="text-xs text-muted">
        Point at a day, or move along with the arrow keys. Up is brighter, down is heavier; a dot is a day with too little writing to read.
      </p>
      <details className="group">
        <summary className="inline-flex cursor-pointer select-none list-none items-center gap-1 rounded text-sm text-muted hover:text-ink [&::-webkit-details-marker]:hidden">
          <ChevronRight size={14} aria-hidden="true" className="transition-transform group-open:rotate-90" />
          The days as a table
        </summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">Each day of {monthName(c.month)}: the mood of your writing and your music</caption>
            <thead className="eyebrow border-b border-line">
              <tr>
                <th scope="col" className="px-2 py-1.5 text-left font-medium">Day</th>
                <th scope="col" className="px-2 py-1.5 text-left font-medium">Writing</th>
                <th scope="col" className="px-2 py-1.5 text-right font-medium">Words</th>
                <th scope="col" className="px-2 py-1.5 text-right font-medium">Music</th>
                <th scope="col" className="px-2 py-1.5 text-right font-medium">Upbeat</th>
                <th scope="col" className="px-2 py-1.5 text-right font-medium">Melancholic</th>
              </tr>
            </thead>
            <tbody>
              {days.map((x) => (
                <tr key={x.day} className="border-b border-line last:border-0">
                  <th scope="row" className="whitespace-nowrap px-2 py-1 text-left font-normal text-ink">
                    {day(x.day)}
                  </th>
                  <td className="px-2 py-1">{dayLine(x)}</td>
                  <td className="num px-2 py-1 text-right">{count(x.words)}</td>
                  <td className="num px-2 py-1 text-right">{amount(x.music_hours)} h</td>
                  <td className="num px-2 py-1 text-right">{x.upbeat === null ? "–" : percent(x.upbeat)}</td>
                  <td className="num px-2 py-1 text-right">{x.melancholic === null ? "–" : percent(x.melancholic)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

/** How mood and music moved together: the notable relations, then every one tried. */
function Relations({ c }: { c: RhythmsMonthCard }) {
  const notable = c.relations.filter((r) => r.notable);
  if (!c.relations.length) return null;
  return (
    <section aria-label="Mood and music together" className="space-y-2.5 border-t border-line pt-4">
      <h4 className="smallcaps flex items-center gap-1.5">
        <Link2 size={14} aria-hidden="true" className="text-muted" />
        Mood and music together
      </h4>
      {notable.length ? (
        <ul className="space-y-2">
          {notable.slice(0, 3).map((r) => (
            <li key={`${r.kind}-${r.music}`} className="break-words text-sm leading-relaxed text-ink/90">
              {r.text}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">Your mood and your music didn&apos;t move together clearly enough this month to say.</p>
      )}
      <details className="group">
        <summary className="inline-flex cursor-pointer select-none list-none items-center gap-1 rounded text-sm text-muted hover:text-ink [&::-webkit-details-marker]:hidden">
          <ChevronRight size={14} aria-hidden="true" className="transition-transform group-open:rotate-90" />
          Every relation tried <span className="num">({c.relations.length})</span>
        </summary>
        <ul className="mt-2 space-y-1.5 pl-5 text-sm text-muted">
          {c.relations.map((r) => (
            <li key={`${r.kind}-${r.music}`} className="list-disc break-words">
              {r.text}
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-muted">
          r runs from −1 to 1: 0 is no link, and the further from 0, the more the two moved together (or, below 0, against each other).
          Many are tried each month, so now and then one looks strong by chance. None says which led.
        </p>
      </details>
    </section>
  );
}

/** One month opened large: its story, then its mood, music and writing, its days, and how they moved together. */
function MonthCard({ c, months }: { c: RhythmsMonthCard; months: RhythmsMonths }) {
  return (
    <article id={CARD_ID} aria-labelledby={`${CARD_ID}-title`} className="min-w-0 space-y-5">
      <header className="space-y-1">
        <h3 id={`${CARD_ID}-title`} className="title-2">
          {monthName(c.month)}
          {!c.complete && <span className="text-muted"> (so far)</span>}
        </h3>
        <p className="text-xs text-muted">
          {c.story.by === "model"
            ? "Written by the model on this computer from the numbers below, never your words."
            : "Written from the numbers below, with no model."}
        </p>
      </header>
      {c.story.text && <p className="break-words font-display text-lg leading-relaxed text-ink">{c.story.text}</p>}
      <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
        <MoodPart c={c} localModel={months.local_model} />
        <MusicPart c={c} musicbrainz={months.musicbrainz} />
        <WritingPart c={c} />
      </div>
      <Days key={c.month} c={c} />
      <Relations c={c} />
    </article>
  );
}

/**
 * A card for each month, newest first, one opened large: how it felt in the user's own writing
 * (VADER on this computer, and the feelings a local model named), what they listened to, how much
 * they wrote, and how mood and music moved together, said without saying which led. The night makes
 * the cards; the page only reads them.
 */
export function Months({ months }: { months: RhythmsMonths }) {
  const [open, setOpen] = useState<string | null>(null);
  const cards = months.cards;
  const waiting = months.held.filter((m) => !cards.some((c) => c.month === m)).length;

  if (!cards.length) {
    return (
      <section aria-label="Months" className="card space-y-2 p-4 sm:p-5">
        <h2 className="smallcaps flex items-center gap-1.5">
          <Library size={14} aria-hidden="true" className="text-muted" />
          Months
        </h2>
        <p className="text-sm text-muted">
          {months.held.length
            ? "No month has a card yet. The night makes one for this month and a few earlier ones each night, newest first; "
            : "A card for each month appears here once there are messages or listening to read; "}
          <code className="text-xs">proxenos clone rhythms --month YYYY-MM</code> makes one now.
        </p>
      </section>
    );
  }

  // Unless one is picked, the newest month with a few days of mood to read: a month just begun has little.
  const shown = cards.find((c) => c.month === open) ?? cards.find((c) => c.mood.days >= OPEN_DAYS) ?? cards[0];
  return (
    <section aria-labelledby="rhythms-months-title" className="card space-y-4 p-4 sm:p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="rhythms-months-title" className="smallcaps flex items-center gap-1.5">
          <Library size={14} aria-hidden="true" className="text-muted" />
          Months
        </h2>
        <p className="text-xs text-muted">How each felt in your own writing, what you listened to and wrote.</p>
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[13rem_minmax(0,1fr)]">
        <ul
          aria-label="Months, newest first"
          className="flex min-w-0 gap-2 overflow-x-auto pb-1 lg:max-h-[48rem] lg:flex-col lg:overflow-x-visible lg:overflow-y-auto lg:pb-0 lg:pr-1"
        >
          {cards.map((c) => (
            <li key={c.month} className="shrink-0">
              <MonthButton c={c} open={c.month === shown.month} onOpen={() => setOpen(c.month)} />
            </li>
          ))}
        </ul>
        <MonthCard c={shown} months={months} />
      </div>
      <p className="text-xs leading-relaxed text-muted">
        Mood is read from your own messages and the mail you sent, never anyone else&apos;s: each sentence is scored on this computer
        from −1 (heavy) to 1 (bright) with VADER, a word list made for short messages, and a day is their mean once it has three.{" "}
        {months.local_model
          ? "The model on this computer names each day's feelings."
          : "Feelings are named only by a model on this computer, so they're left out: your words never go to a hosted one."}{" "}
        Genres and moods of music are the model&apos;s, from artists&apos; names
        {months.musicbrainz && (
          <>
            ; kinds of music are{" "}
            <a href="https://musicbrainz.org" className="underline decoration-line-strong underline-offset-2 hover:text-ink">
              MusicBrainz
            </a>
            &apos;s genres, looked up by artist name alone (CC BY-NC-SA)
          </>
        )}
        .{waiting > 0 && ` ${plural(waiting, "more month")} ${waiting === 1 ? "waits" : "wait"} for a card; the night makes a few each night.`}
      </p>
    </section>
  );
}
