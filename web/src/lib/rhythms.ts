// Server side of the Rhythms view. Import only from route handlers.
//
// The page reads the weeks through `proxenos clone rhythms --json`, which counts again only the
// month files that changed since it last ran (the first run over years of records takes longer)
// and asks no model. Its answer is read field by field, so nothing else in it reaches the page:
// counts, hours and km, the channels' names, the artists' names and their genres and moods, and
// the month cards the night made: numbers, labels, artists' names and each card's story, never
// anyone's words.

import { lastLine, NO_COMMAND } from "./connect";
import type {
  RhythmsLine,
  RhythmsMonthCard,
  RhythmsMonthDay,
  RhythmsMonths,
  RhythmsMoodWeek,
  RhythmsMove,
  RhythmsRange,
  RhythmsRelation,
  RhythmsResolution,
  RhythmsResponse,
  RhythmsShare,
  RhythmsWeek,
} from "./types";
import { nowIso, proxenos, vaultInfo, vaultPath } from "./vault";

const COUNT_MS = 5 * 60_000; // the first count reads every month file: a minute or two over years
const MAX_OUTPUT = 64 * 1024 * 1024;
const WEEK = /^\d{4}-W\d{2}$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const RANGES: RhythmsRange[] = ["3m", "1y", "all"];
const RESOLUTIONS: RhythmsResolution[] = ["1w", "2w", "1m"];
const KINDS = new Set<RhythmsLine["kind"]>(["listening", "riding", "messages", "mood"]);
const MONTH = /^\d{4}-\d{2}$/;
const RELATIONS = new Set<RhythmsRelation["kind"]>(["same day", "music then mood", "mood then music", "with", "next day with"]);
const MAX_CARDS = 600; // fifty years of months

function record(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function num(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : 0;
}

function str(v: unknown, max = 200): string {
  return typeof v === "string" ? v.slice(0, max) : "";
}

/** A {name: number} map, at most `max` entries, numbers only. */
function counts(v: unknown, max = 40): Record<string, number> {
  const found: Record<string, number> = {};
  for (const [k, n] of Object.entries(record(v)).slice(0, max)) found[k.slice(0, 80)] = num(n);
  return found;
}

function move(v: unknown): RhythmsMove {
  const r = record(v);
  return { count: num(r.count), km: num(r.km), hours: num(r.hours) };
}

function toWeek(raw: unknown): RhythmsWeek | null {
  const r = record(raw);
  const week = str(r.week);
  const start = str(r.start);
  if (!WEEK.test(week) || !DAY.test(start)) return null;
  const heard = record(r.listening);
  const moved = record(r.movement);
  const said = record(r.messages);
  const met = record(r.calendar);
  return {
    week,
    start,
    listening: {
      hours: num(heard.hours),
      spoken_hours: num(heard.spoken_hours),
      plays: num(heard.plays),
      artists: num(heard.artists),
      top: (Array.isArray(heard.top) ? heard.top : [])
        .slice(0, 5)
        .map((a) => ({ name: str(record(a).name), hours: num(record(a).hours) }))
        .filter((a) => a.name),
      genres: counts(heard.genres),
      moods: counts(heard.moods),
      top_genre: str(heard.top_genre, 40) || null,
      top_mood: str(heard.top_mood, 40) || null,
    },
    movement: {
      rides: { ...move(moved.rides), climb_m: num(record(moved.rides).climb_m) },
      runs: move(moved.runs),
      hikes: move(moved.hikes),
      walks: move(moved.walks),
      other: { count: num(record(moved.other).count), hours: num(record(moved.other).hours) },
    },
    messages: { sent: counts(said.sent), received: counts(said.received), people: num(said.people) },
    calendar: { events: num(met.events), hours: num(met.hours) },
  };
}

/** A number that may be negative (a valence, an r), or null. */
function signed(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function list(v: unknown, max: number): unknown[] {
  return Array.isArray(v) ? v.slice(0, max) : [];
}

function names(v: unknown, max: number): string[] {
  return list(v, max)
    .map((s) => str(s, 40))
    .filter(Boolean);
}

function shares(v: unknown): RhythmsShare[] {
  return list(v, 10)
    .map((s) => ({ name: str(record(s).name, 80), hours: num(record(s).hours), share: Math.min(1, num(record(s).share)) }))
    .filter((s) => s.name);
}

function moodWeek(v: unknown): RhythmsMoodWeek | null {
  const w = record(v);
  const valence = signed(w.valence);
  if (!DAY.test(str(w.start)) || valence === null) return null;
  return { start: str(w.start), valence, days: num(w.days), emotion: str(w.emotion, 40) || null };
}

function toDay(v: unknown): RhythmsMonthDay | null {
  const d = record(v);
  if (!DAY.test(str(d.day))) return null;
  const share = (x: unknown) => (signed(x) === null ? null : Math.min(1, num(x)));
  return {
    day: str(d.day),
    valence: signed(d.valence),
    scored: num(d.scored),
    emotions: names(d.emotions, 3),
    words: num(d.words),
    music_hours: num(d.music_hours),
    upbeat: share(d.upbeat),
    melancholic: share(d.melancholic),
  };
}

function toRelation(v: unknown): RhythmsRelation | null {
  const r = record(v);
  const kind = str(r.kind) as RhythmsRelation["kind"];
  const value = signed(r.r);
  const text = str(r.text, 600);
  if (!RELATIONS.has(kind) || value === null || !text) return null;
  return { kind, music: str(r.music, 80), r: value, n: num(r.n), p: signed(r.p), notable: r.notable === true, text };
}

function toCard(v: unknown): RhythmsMonthCard | null {
  const c = record(v);
  if (!MONTH.test(str(c.month))) return null;
  const m = record(c.mood);
  const arc = record(m.arc);
  const tone = record(m.tone);
  const spread = record(m.variability);
  const heard = record(c.music);
  const w = record(c.writing);
  const story = record(c.story);
  const counted = (x: unknown) => ({ count: num(record(x).count), words: num(record(x).words) });
  return {
    month: str(c.month),
    generated: str(c.generated, 40),
    complete: c.complete === true,
    mood: {
      days: num(m.days),
      valence: signed(m.valence),
      labelled_days: num(m.labelled_days),
      top: list(m.top, 3)
        .map((t) => ({
          name: str(record(t).name, 40),
          days: num(record(t).days),
          share: Math.min(1, num(record(t).share)),
          bright: record(t).bright === true,
        }))
        .filter((t) => t.name),
      tone: { brighter: num(tone.brighter), mixed: num(tone.mixed), heavier: num(tone.heavier) },
      arc: {
        weeks: list(arc.weeks, 6)
          .map(moodWeek)
          .filter((x): x is RhythmsMoodWeek => x !== null),
        best: moodWeek(arc.best),
        hardest: moodWeek(arc.hardest),
      },
      variability: { sd: signed(spread.sd), word: str(spread.word, 40) || null },
      usual_sd: signed(m.usual_sd),
      by_model: m.by_model === true,
    },
    music: {
      hours: num(heard.hours),
      music_hours: num(heard.music_hours),
      spoken_hours: num(heard.spoken_hours),
      plays: num(heard.plays),
      artists: num(heard.artists),
      top_artists: list(heard.top_artists, 5)
        .map((a) => ({ name: str(record(a).name, 80), hours: num(record(a).hours) }))
        .filter((a) => a.name),
      genres: shares(heard.genres),
      kinds: shares(heard.kinds),
      moods: shares(heard.moods),
      labelled: Math.min(1, num(heard.labelled)),
    },
    writing: {
      words: num(w.words),
      channels: list(w.channels, 12)
        .map((ch) => ({ name: str(record(ch).name, 40), words: num(record(ch).words), pieces: num(record(ch).pieces) }))
        .filter((ch) => ch.name),
      notes: counted(w.notes),
      documents: counted(w.documents),
      usual: signed(w.usual),
      usual_by_now: signed(w.usual_by_now),
      beside_usual: signed(w.beside_usual),
    },
    relations: list(c.relations, 40)
      .map(toRelation)
      .filter((r): r is RhythmsRelation => r !== null),
    story: { by: story.by === "model" ? "model" : "numbers", text: str(story.text, 1500) },
    waits_on_model: c.waits_on_model === true,
    days: list(c.days, 31)
      .map(toDay)
      .filter((d): d is RhythmsMonthDay => d !== null),
  };
}

function toMonths(v: unknown): RhythmsMonths {
  const r = record(v);
  return {
    held: list(r.held, MAX_CARDS)
      .map((m) => str(m, 7))
      .filter((m) => MONTH.test(m)),
    cards: list(r.cards, MAX_CARDS)
      .map(toCard)
      .filter((c): c is RhythmsMonthCard => c !== null),
    local_model: r.local_model === true,
    musicbrainz: r.musicbrainz === true,
  };
}

function toLines(v: unknown): RhythmsLine[] {
  return (Array.isArray(v) ? v : [])
    .map((l) => ({ kind: str(record(l).kind) as RhythmsLine["kind"], text: str(record(l).text, 600) }))
    .filter((l) => KINDS.has(l.kind) && l.text);
}

function empty(): RhythmsResponse["stands_out"] {
  const none = () => ({ "1w": [], "2w": [], "1m": [] });
  return { "3m": none(), "1y": none(), all: none() };
}

/** The weeks, from `proxenos clone rhythms --json`; an empty answer with why, when there's none. */
export async function getRhythms(): Promise<RhythmsResponse> {
  const vault = vaultPath();
  const info = await vaultInfo(vault);
  const answer: RhythmsResponse = {
    now: nowIso(),
    vault: info,
    today: "",
    weeks: [],
    months: { held: [], cards: [], local_model: false, musicbrainz: false },
    people: { "2w": {}, "1m": {} },
    channels: [],
    coverage: { share: 0, artists: 0, labelled: 0 },
    model: false,
    stands_out: empty(),
    error: null,
  };
  if (!info.exists) return answer;
  const cli = await proxenos();
  if (!cli) return { ...answer, error: NO_COMMAND };
  const ran = await new Promise<{ out: string } | { error: string }>((resolve) => {
    cli.exec(["clone", "rhythms", "--json"], { timeout: COUNT_MS, maxBuffer: MAX_OUTPUT }, (error, stdout, stderr) => {
      if (!error) resolve({ out: stdout });
      else resolve({ error: error.killed ? "It took too long." : lastLine(stderr) || lastLine(stdout) || "It failed." });
    });
  });
  if ("error" in ran) return { ...answer, error: `Couldn't count your weeks: ${ran.error}` };
  let r: Record<string, unknown>;
  try {
    r = record(JSON.parse(ran.out));
  } catch {
    return { ...answer, error: "proxenos clone rhythms gave an answer this page can't read." };
  }
  const people = record(r.people);
  const coverage = record(r.coverage);
  const stands = record(r.stands_out);
  const out = empty();
  for (const range of RANGES) for (const res of RESOLUTIONS) out[range][res] = toLines(record(stands[range])[res]);
  return {
    ...answer,
    today: DAY.test(str(r.today)) ? str(r.today) : "",
    weeks: (Array.isArray(r.weeks) ? r.weeks : []).map(toWeek).filter((w): w is RhythmsWeek => w !== null),
    months: toMonths(r.months),
    people: { "2w": counts(people["2w"], 100_000), "1m": counts(people["1m"], 100_000) },
    channels: (Array.isArray(r.channels) ? r.channels : []).map((c) => str(c, 40)).filter(Boolean).slice(0, 20),
    coverage: { share: Math.min(1, num(coverage.share)), artists: num(coverage.artists), labelled: num(coverage.labelled) },
    model: r.model === true,
    stands_out: out,
  };
}
