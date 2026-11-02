// The Rhythms view's periods, made in the page from the weekly series: a week, two weeks or a
// month at a time. They're grouped as the rhythms clone groups them for what stands out
// (proxenos/clones/rhythms.py: `period` and `in_range`), so the lines and the charts agree: two
// weeks count from Monday 2001-01-01, a week is in the month its Thursday is in, and a range
// reaches back to the start of its first period, so every period shown is whole.

import type { RhythmsRange, RhythmsResolution, RhythmsResponse, RhythmsWeek } from "./types";

const DAY_MS = 86_400_000;
const EPOCH = Date.UTC(2001, 0, 1); // a Monday
export const RANGE_WEEKS: Record<RhythmsRange, number | null> = { "3m": 13, "1y": 52, all: null };
export const UNLABELLED = "unlabelled";

export interface Period {
  key: string;
  /** As a sentence names it: "the week of Mar 2, 2026", "Mar 2 to 15, 2026", "March 2026". */
  label: string;
  /** Under a chart: "Mar 2", "Mar". */
  tick: string;
  year: number;
  start: string; // its first Monday
  weeks: number;
  /** Whether it holds this week, which isn't over. */
  current: boolean;
  hours: number;
  plays: number;
  top: { name: string; hours: number }[];
  genres: Record<string, number>;
  moods: Record<string, number>;
  topGenre: string | null;
  topMood: string | null;
  rides: { count: number; km: number; hours: number; climb: number };
  /** Runs, hikes and walks. */
  moved: { count: number; km: number };
  sent: Record<string, number>;
  received: Record<string, number>;
  sentTotal: number;
  receivedTotal: number;
  /** People and chats written to; null where the clone didn't count it. */
  people: number | null;
  events: number;
  eventHours: number;
}

function dayMs(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

function isoDay(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

/** The period a week falls in, keyed as the clone keys it. */
export function periodKey(week: RhythmsWeek, resolution: RhythmsResolution): string {
  if (resolution === "1w") return week.week;
  const ms = dayMs(week.start);
  if (resolution === "2w") return isoDay(EPOCH + Math.floor((ms - EPOCH) / (14 * DAY_MS)) * 14 * DAY_MS);
  return isoDay(ms + 3 * DAY_MS).slice(0, 7);
}

/** The weeks of a range, widened back to the start of its first period. */
export function inRange(weeks: RhythmsWeek[], range: RhythmsRange, resolution: RhythmsResolution): RhythmsWeek[] {
  const back = RANGE_WEEKS[range];
  if (back === null || weeks.length <= back) return weeks;
  let first = weeks.length - back;
  const key = periodKey(weeks[first], resolution);
  while (first > 0 && periodKey(weeks[first - 1], resolution) === key) first -= 1;
  return weeks.slice(first);
}

function add(into: Record<string, number>, from: Record<string, number>): void {
  for (const [k, v] of Object.entries(from)) into[k] = (into[k] ?? 0) + v;
}

/** The biggest labelled entry: never "unlabelled". */
function topOf(mix: Record<string, number>): string | null {
  let best: string | null = null;
  for (const [k, v] of Object.entries(mix)) if (k !== UNLABELLED && v > 0 && (best === null || v > mix[best])) best = k;
  return best;
}

function sum(values: Record<string, number>): number {
  return Object.values(values).reduce((a, b) => a + b, 0);
}

function fmt(ms: number, opts: Intl.DateTimeFormatOptions): string {
  return new Date(ms).toLocaleDateString("en-US", { timeZone: "UTC", ...opts });
}

function naming(resolution: RhythmsResolution, first: number, last: number): { label: string; tick: string } {
  const sunday = last + 6 * DAY_MS;
  if (resolution === "1m") {
    const month = first + 3 * DAY_MS;
    return { label: fmt(month, { month: "long", year: "numeric" }), tick: fmt(month, { month: "short" }) };
  }
  const tick = fmt(first, { month: "short", day: "numeric" });
  if (resolution === "1w") return { label: `the week of ${fmt(first, { month: "short", day: "numeric", year: "numeric" })}`, tick };
  const sameMonth = fmt(first, { month: "short" }) === fmt(sunday, { month: "short" });
  const day = new Date(sunday).getUTCDate();
  const end = `${sameMonth ? day : fmt(sunday, { month: "short", day: "numeric" })}, ${new Date(sunday).getUTCFullYear()}`;
  return { label: `${tick} to ${end}`, tick };
}

/** The weeks of a range as periods, oldest first. The last week of the series is this one. */
export function periods(data: RhythmsResponse, range: RhythmsRange, resolution: RhythmsResolution): Period[] {
  const shown = inRange(data.weeks, range, resolution);
  const thisWeek = data.weeks[data.weeks.length - 1]?.week;
  const groups: RhythmsWeek[][] = [];
  let last: string | null = null;
  for (const w of shown) {
    const key = periodKey(w, resolution);
    if (key !== last) groups.push([]);
    groups[groups.length - 1].push(w);
    last = key;
  }
  return groups.map((group) => {
    const key = periodKey(group[0], resolution);
    const first = dayMs(group[0].start);
    const genres: Record<string, number> = {};
    const moods: Record<string, number> = {};
    const heard: Record<string, number> = {};
    const sent: Record<string, number> = {};
    const received: Record<string, number> = {};
    const p = {
      hours: 0,
      plays: 0,
      rides: { count: 0, km: 0, hours: 0, climb: 0 },
      moved: { count: 0, km: 0 },
      events: 0,
      eventHours: 0,
    };
    for (const w of group) {
      const l = w.listening;
      p.hours += l.hours;
      p.plays += l.plays;
      add(genres, l.genres);
      add(moods, l.moods);
      for (const a of l.top) heard[a.name] = (heard[a.name] ?? 0) + a.hours;
      const m = w.movement;
      p.rides.count += m.rides.count;
      p.rides.km += m.rides.km;
      p.rides.hours += m.rides.hours;
      p.rides.climb += m.rides.climb_m;
      for (const kind of [m.runs, m.hikes, m.walks]) {
        p.moved.count += kind.count;
        p.moved.km += kind.km;
      }
      add(sent, w.messages.sent);
      add(received, w.messages.received);
      p.events += w.calendar.events;
      p.eventHours += w.calendar.hours;
    }
    const people =
      resolution === "1w" ? group[0].messages.people : resolution === "2w" ? (data.people["2w"][key] ?? 0) : (data.people["1m"][key] ?? 0);
    return {
      key,
      ...naming(resolution, first, dayMs(group[group.length - 1].start)),
      year: new Date(first + 3 * DAY_MS).getUTCFullYear(),
      start: group[0].start,
      weeks: group.length,
      current: group.some((w) => w.week === thisWeek),
      ...p,
      top: Object.entries(heard)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
        .map(([name, hours]) => ({ name, hours })),
      genres,
      moods,
      topGenre: topOf(genres),
      topMood: topOf(moods),
      sent,
      received,
      sentTotal: sum(sent),
      receivedTotal: sum(received),
      people,
    };
  });
}
