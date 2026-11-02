"use client";

import { useMemo, useState } from "react";
import { AudioWaveform, Bike, Headphones, MessageSquare, Smile, type LucideIcon } from "lucide-react";

import { Columns } from "@/components/charts/Columns";
import { EmptyState, ErrorBanner, NoVault } from "@/components/EmptyState";
import { Segmented } from "@/components/layout/Segmented";
import { ProseSkeleton } from "@/components/Skeleton";
import { useRhythms } from "@/lib/client";
import { periods, UNLABELLED, type Period } from "@/lib/rhythmsPeriods";
import type { RhythmsLine, RhythmsRange, RhythmsResolution } from "@/lib/types";
import { cn } from "@/lib/utils";

const RESOLUTIONS: { id: RhythmsResolution; label: string }[] = [
  { id: "1w", label: "1 week" },
  { id: "2w", label: "2 weeks" },
  { id: "1m", label: "1 month" },
];
const RANGES: { id: RhythmsRange; label: string }[] = [
  { id: "3m", label: "3 months" },
  { id: "1y", label: "1 year" },
  { id: "all", label: "All" },
];
const KIND_ICON: Record<RhythmsLine["kind"], LucideIcon> = {
  listening: Headphones,
  riding: Bike,
  messages: MessageSquare,
  mood: Smile,
};
const CHANNEL_CHARTS = 3; // channels charted one by one; the rest fold into one
const TABLE_ROWS = 26;
const NIGHT_LABELS = 300; // the clone's LABEL: artists the night labels

/** 0.4, 3.5, 12, 1,240: a decimal only where it says something. */
function amount(v: number): string {
  if (v === 0) return "0";
  return v < 10 ? v.toFixed(1) : Math.round(v).toLocaleString("en-US");
}

function count(v: number): string {
  return v.toLocaleString("en-US");
}

function capital(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function Chip({ label, value }: { label: string; value: string | null }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-line-strong bg-surface-2 px-2.5 py-0.5 text-xs">
      <span className="text-muted">{label}</span>
      <span className={value ? "text-ink" : "text-faint"}>{value ?? UNLABELLED}</span>
    </span>
  );
}

interface Row {
  id: string;
  label: string;
  values: number[];
  max?: number;
  format: (v: number) => string;
  /** The picked period's value, beside the row's name. */
  shown: (p: Period) => string;
}

/** The charts' rows: listening, rides, the rest of moving about, and messages sent by channel. */
function rowsFor(ps: Period[], channels: string[]): Row[] {
  const hours = (v: number) => `${amount(v)} h`;
  const km = (v: number) => `${amount(v)} km`;
  const rows: Row[] = [
    { id: "listening", label: "Listening", values: ps.map((p) => p.hours), format: hours, shown: (p) => hours(p.hours) },
    { id: "rides", label: "Rides", values: ps.map((p) => p.rides.km), format: km, shown: (p) => km(p.rides.km) },
  ];
  if (ps.some((p) => p.moved.km > 0)) {
    rows.push({
      id: "moved",
      label: "Runs, hikes and walks",
      values: ps.map((p) => p.moved.km),
      format: km,
      shown: (p) => km(p.moved.km),
    });
  }
  const sending = channels.filter((c) => ps.some((p) => (p.sent[c] ?? 0) > 0));
  const own = sending.slice(0, sending.length > CHANNEL_CHARTS + 1 ? CHANNEL_CHARTS : CHANNEL_CHARTS + 1);
  const rest = sending.filter((c) => !own.includes(c));
  const sent = (p: Period, cs: string[]) => cs.reduce((n, c) => n + (p.sent[c] ?? 0), 0);
  const series = [...own.map((c) => ({ id: c, label: `Sent on ${c}`, of: [c] }))];
  if (rest.length) series.push({ id: "elsewhere", label: `Sent on ${rest.join(", ")}`, of: rest });
  const max = Math.max(1, ...series.flatMap((s) => ps.map((p) => sent(p, s.of))));
  for (const s of series) {
    rows.push({
      id: `sent-${s.id}`,
      label: s.label,
      values: ps.map((p) => sent(p, s.of)),
      max, // one scale for every channel, so their heights compare
      format: (v) => count(Math.round(v)),
      shown: (p) => count(sent(p, s.of)),
    });
  }
  return rows;
}

/** Where a few periods are named under the charts: the first, the last, and evenly between. */
function ticks(ps: Period[]): { i: number; text: string }[] {
  if (!ps.length) return [];
  const every = Math.max(1, Math.ceil(ps.length / 6));
  const found: { i: number; text: string }[] = [];
  for (let i = 0; i < ps.length; i += every) {
    const yearTurned = i === 0 || ps[i].year !== ps[i - every]?.year;
    found.push({ i, text: yearTurned ? `${ps[i].tick} ${ps[i].year}` : ps[i].tick });
  }
  return found;
}

/** The picked period: its genre, mood and top artist, and every count beside them. */
function Readout({ p }: { p: Period }) {
  const facts: [string, string][] = [
    ["Listening", `${amount(p.hours)} h`],
    ["Rides", `${count(p.rides.count)} · ${amount(p.rides.km)} km`],
    ["On foot", `${amount(p.moved.km)} km`],
    ["Sent", count(p.sentTotal)],
    ["Received", count(p.receivedTotal)],
    ["Wrote to", p.people === null ? "–" : count(p.people)],
    ["Events", `${count(p.events)} · ${amount(p.eventHours)} h`],
  ];
  return (
    <div className="space-y-3" aria-live="polite">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 className="title-3">
          {capital(p.label)}
          {p.current && <span className="text-muted"> (so far)</span>}
        </h3>
        {p.top[0] && (
          <span className="min-w-0 truncate text-sm text-muted">
            Most played <span className="text-ink">{p.top[0].name}</span>
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        <Chip label="Genre" value={p.topGenre} />
        <Chip label="Mood" value={p.topMood} />
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
        {facts.map(([k, v]) => (
          <div key={k}>
            <dt className="eyebrow">{k}</dt>
            <dd className="num text-sm text-ink">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** Every period of the range, newest first: what each chart shows, and its genre, mood and artist. */
function Table({ ps, picked, onPick }: { ps: Period[]; picked: number; onPick: (i: number) => void }) {
  const [all, setAll] = useState(false);
  const newest = ps.map((p, i) => ({ p, i })).reverse();
  const listed = all ? newest : newest.slice(0, TABLE_ROWS);
  const th = "px-2 py-2 text-left font-medium";
  const td = "px-2 py-1.5 whitespace-nowrap";
  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="eyebrow border-b border-line">
            <tr>
              <th className={th}>{ps[0]?.label.startsWith("the week of") ? "Week of" : "Period"}</th>
              <th className={cn(th, "text-right")}>Listening</th>
              <th className={th}>Most played</th>
              <th className={th}>Genre</th>
              <th className={th}>Mood</th>
              <th className={cn(th, "text-right")}>Rides</th>
              <th className={cn(th, "text-right")}>On foot</th>
              <th className={cn(th, "text-right")}>Sent</th>
              <th className={cn(th, "text-right")}>Received</th>
              <th className={cn(th, "text-right")}>Wrote to</th>
              <th className={cn(th, "text-right")}>Events</th>
            </tr>
          </thead>
          <tbody>
            {listed.map(({ p, i }) => (
              <tr
                key={p.key}
                onClick={() => onPick(i)}
                className={cn("cursor-pointer border-b border-line last:border-0 hover:bg-surface-2", i === picked && "bg-surface-2")}
              >
                <td className={cn(td, "text-ink")}>
                  {capital(p.label.replace(/^the week of /, ""))}
                  {p.current && <span className="text-muted"> (so far)</span>}
                </td>
                <td className={cn(td, "num text-right")}>{amount(p.hours)} h</td>
                <td className={cn(td, "max-w-40 truncate")}>{p.top[0]?.name ?? "–"}</td>
                <td className={cn(td, p.topGenre ? "text-ink" : "text-faint")}>{p.topGenre ?? UNLABELLED}</td>
                <td className={cn(td, p.topMood ? "text-ink" : "text-faint")}>{p.topMood ?? UNLABELLED}</td>
                <td className={cn(td, "num text-right")}>
                  {p.rides.count ? `${p.rides.count} · ${amount(p.rides.km)} km` : "–"}
                </td>
                <td className={cn(td, "num text-right")}>{p.moved.km ? `${amount(p.moved.km)} km` : "–"}</td>
                <td className={cn(td, "num text-right")}>{count(p.sentTotal)}</td>
                <td className={cn(td, "num text-right")}>{count(p.receivedTotal)}</td>
                <td className={cn(td, "num text-right")}>{p.people === null ? "–" : count(p.people)}</td>
                <td className={cn(td, "num text-right")}>{count(p.events)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {newest.length > TABLE_ROWS && (
        <button
          type="button"
          onClick={() => setAll((a) => !a)}
          className="w-full border-t border-line px-4 py-2 text-left text-sm text-muted hover:text-ink"
        >
          {all ? "Show the newest only" : `Show all ${count(newest.length)} periods`}
        </button>
      )}
    </div>
  );
}

/**
 * Your weeks over time, side by side: how much you listened and to what genre and mood, how far you
 * rode, ran and walked, and how many messages you sent on each channel, a week, two weeks or a month
 * at a time, over three months, a year or everything. The counts come from the rhythms clone with no
 * model; an artist's genre and moods are the model's, given only their name. What stands out is
 * written in plain words from the counts, and says what happened, never why.
 */
export function Rhythms() {
  const { data, error, clearError } = useRhythms();
  const [resolution, setResolution] = useState<RhythmsResolution>("1w");
  const [range, setRange] = useState<RhythmsRange>("1y");
  const [hover, setHover] = useState<number | null>(null);
  const [pick, setPick] = useState<{ key: string; i: number } | null>(null);

  const ps = useMemo(() => (data ? periods(data, range, resolution) : []), [data, range, resolution]);
  const rows = useMemo(() => rowsFor(ps, data?.channels ?? []), [ps, data?.channels]);

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load your weeks: ${error}`} /> : <ProseSkeleton label="Counting your weeks" />;
  }
  if (!data.vault.exists) return <NoVault path={data.vault.path} />;

  const banners = (
    <>
      {error && <ErrorBanner message={error} onDismiss={clearError} />}
      {data.error && <ErrorBanner message={data.error} />}
    </>
  );

  if (data.weeks.length === 0) {
    return (
      <div className="p-4 sm:p-6">
        {banners}
        <EmptyState icon={AudioWaveform} title="No weeks to show yet" command="proxenos clone rhythms">
          Rhythms lays your weeks side by side: your listening from Spotify, with its genres and moods, your rides, runs and walks from
          Strava, and the messages you sent and got on each channel. Bring in a source on Connect, and the weeks fill in.
        </EmptyState>
      </div>
    );
  }

  const filterKey = `${range}:${resolution}`;
  // Unless one is picked, the newest period that holds anything: this week may hold nothing yet.
  const held = ps.findLastIndex((p) => p.hours + p.rides.km + p.moved.km + p.sentTotal + p.receivedTotal > 0);
  const picked = pick && pick.key === filterKey && pick.i < ps.length ? pick.i : held >= 0 ? held : ps.length - 1;
  const shown = hover ?? picked;
  const lines = data.stands_out[range][resolution];
  const cover = data.coverage;
  const unit = resolution === "1w" ? "week" : resolution === "2w" ? "two weeks" : "month";

  return (
    <div className="mx-auto max-w-5xl space-y-5 p-4 pb-24 sm:p-6 md:pb-20">
      {banners}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Segmented
          label="Resolution"
          tabs={RESOLUTIONS}
          value={resolution}
          onChange={(r) => {
            setResolution(r);
            setHover(null);
          }}
        />
        <Segmented
          label="Range"
          tabs={RANGES}
          value={range}
          onChange={(r) => {
            setRange(r);
            setHover(null);
          }}
        />
      </div>

      {cover.artists > 0 && (
        <p className="text-xs text-muted">
          {cover.labelled === 0 && !data.model ? (
            <>No model is set up, so genres and moods are unlabelled; everything else is counted.</>
          ) : cover.labelled === cover.artists ? (
            <>Every artist you listened to has a genre and moods, labelled by the model from their name alone.</>
          ) : (
            <>
              Genres and moods cover <span className="num text-ink">{Math.round(cover.share * 100)}%</span> of your listening time (
              <span className="num">{count(cover.labelled)}</span> of <span className="num">{count(cover.artists)}</span> artists), labelled by
              the model from their names alone. The night labels up to {NIGHT_LABELS} more, the most played first.
            </>
          )}
        </p>
      )}

      {lines.length > 0 && (
        <section aria-label="What stands out" className="card space-y-3 p-4 sm:p-5">
          <h2 className="smallcaps">What stands out</h2>
          <ul className="space-y-2.5">
            {lines.map((l) => {
              const Icon = KIND_ICON[l.kind];
              return (
                <li key={l.kind} className="flex gap-3 text-sm leading-relaxed text-ink/90">
                  <Icon size={16} className="mt-0.5 shrink-0 text-muted" aria-hidden="true" />
                  <span className="break-words">{l.text}</span>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <section aria-label="Over time" className="card space-y-5 p-4 sm:p-5">
        {ps[shown] && <Readout p={ps[shown]} />}
        <div className="space-y-4 border-t border-line pt-4">
          {rows.map((row) => (
            <div key={row.id} className="space-y-1.5">
              <div className="flex items-baseline justify-between gap-3 pr-14">
                <span className="smallcaps truncate">{row.label}</span>
                {ps[shown] && <span className="num shrink-0 text-xs text-ink">{row.shown(ps[shown])}</span>}
              </div>
              <Columns
                values={row.values}
                label={`${row.label}, by ${unit}`}
                picked={shown}
                max={row.max}
                format={row.format}
                onHover={setHover}
                onPick={(i) => setPick({ key: filterKey, i })}
              />
            </div>
          ))}
          <div className="relative mr-14 h-4 text-[0.6875rem] text-faint" aria-hidden="true">
            {ticks(ps).map((t, k) => (
              <span
                key={t.i}
                className={cn("num absolute top-0 whitespace-nowrap", k % 2 === 1 && "hidden sm:block")}
                style={{ left: `${((t.i + 0.5) / ps.length) * 100}%`, transform: t.i === 0 ? "none" : "translateX(-50%)" }}
              >
                {t.text}
              </span>
            ))}
          </div>
        </div>
        <p className="text-xs text-muted">
          Point at a {unit} or pick a row below to see it. Each chart has its own scale; the channels share one.
        </p>
      </section>

      <Table ps={ps} picked={picked} onPick={(i) => setPick({ key: filterKey, i })} />
    </div>
  );
}
