"use client";

import {
  ArrowRight,
  Brain,
  CalendarDays,
  HeartPulse,
  type LucideIcon,
  Lightbulb,
  ListTodo,
  Network as NetworkIcon,
  PenLine,
  Radar,
  Rss,
  TrendingUp,
  UserRound,
} from "lucide-react";

import { SuggestionCard } from "@/components/advice/SuggestionCard";
import { ReviewBar } from "@/components/charts/ReviewBar";
import { Sparkline } from "@/components/charts/Sparkline";
import { ChannelBadge, KindBadge } from "@/components/drafts/badges";
import { ErrorBanner, NoVault, QuietLine } from "@/components/EmptyState";
import { TitleLink } from "@/components/feed/ItemCard";
import type { View } from "@/components/layout/nav";
import { Markdown } from "@/components/Markdown";
import { Marked } from "@/components/memory/Marked";
import { whoWhere } from "@/components/memory/ResultRow";
import { NetworkThumb } from "@/components/network/NetworkThumb";
import { Bone, HomeSkeleton } from "@/components/Skeleton";
import { SourceBadge, SourceChip, SourceIcon, sourceMeta } from "@/components/SourceBadge";
import { TaskRow } from "@/components/tasks/TaskRow";
import { NowNote } from "@/components/home/NowNote";
import { careDue, careStatus, firstSentence, mostUrgent, yourMoves } from "@/lib/careClient";
import { sendFeedback, useJson, type useHome } from "@/lib/client";
import {
  formatDateTime,
  freshness,
  greeting,
  hoursSince,
  joinAnd,
  localDay,
  longDay,
  percent,
  shortDate,
  sourceLabel,
  timeAgo,
} from "@/lib/format";
import { plain } from "@/lib/memoryMarks";
import { byUrgency, daysLeft, isUrgent } from "@/lib/tasks";
import type {
  AgendaEvent,
  BriefingResponse,
  CareResponse,
  Draft,
  FeedItem,
  HomeResponse,
  RecallKind,
  RecallResponse,
  RecallTrigger,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type HomeState = ReturnType<typeof useHome>;
type Briefing = ReturnType<typeof useJson<BriefingResponse>>;

interface HomeProps {
  home: HomeState;
  onNavigate: (view: View) => void;
  /** Open the memory view, on one record's conversation when `id` is given. */
  onMemory: (query: string, id?: string) => void;
}

// ── Layout pieces ───────────────────────────────────────────────────────────

/** A labelled band of the briefing: a small-caps label on a hairline, then its cards. */
function Section({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="mt-10 first:mt-0">
      <div className="mb-3.5 flex items-center gap-3">
        <h2 id={id} className="smallcaps whitespace-nowrap">
          {label}
        </h2>
        <span className="h-px flex-1 bg-line" aria-hidden="true" />
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-6 xl:grid-cols-12">{children}</div>
    </section>
  );
}

type Tier = "priority" | "default" | "quiet";

/** One card: an icon, a small-caps kicker over a serif title, a link to the full view, and content. */
function Card({
  icon: Icon,
  kicker,
  title,
  count,
  link,
  onLink,
  tier = "default",
  className,
  children,
}: {
  icon: LucideIcon;
  kicker?: string;
  title: string;
  count?: string | number;
  link?: string;
  onLink?: () => void;
  tier?: Tier;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <article
      className={cn(
        "card card-hover flex min-w-0 flex-col p-4 sm:p-5",
        tier === "priority" && "card-priority",
        tier === "quiet" && "card-quiet",
        className,
      )}
    >
      <header className="mb-4 flex items-start gap-3">
        <span
          className={cn(
            "flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl border",
            tier === "priority" ? "border-accent/30 bg-accent/12 text-accent" : "border-line-strong bg-surface-2 text-muted",
          )}
          aria-hidden="true"
        >
          <Icon size={17} />
        </span>
        <div className="min-w-0 flex-1">
          {kicker && <p className={cn("smallcaps", tier === "priority" && "text-accent")}>{kicker}</p>}
          <h3 className="title-2 flex flex-wrap items-baseline gap-x-2">
            <span className="min-w-0">{title}</span>
            {count !== undefined && <span className="num text-base text-muted">{count}</span>}
          </h3>
        </div>
        {link && onLink && (
          <button
            onClick={onLink}
            aria-label={link}
            className="group -mr-1 mt-0.5 inline-flex h-8 w-8 flex-shrink-0 items-center justify-center gap-1 whitespace-nowrap rounded-full text-sm text-accent underline-offset-4 hover:bg-accent/10 sm:mr-0 sm:mt-1 sm:h-auto sm:w-auto sm:rounded-md sm:hover:bg-transparent sm:hover:underline"
          >
            <span className="hidden sm:inline">{link}</span>
            <ArrowRight size={15} className="transition-transform motion-safe:group-hover:translate-x-0.5" />
          </button>
        )}
      </header>
      <div className="flex-1 space-y-3.5">{children}</div>
    </article>
  );
}

function Meta({ children, className }: { children: React.ReactNode; className?: string }) {
  return <p className={cn("text-sm leading-relaxed text-muted", className)}>{children}</p>;
}

// ── Greeting ────────────────────────────────────────────────────────────────

/** Today's events in the reader's day: all-day ones and those not yet over an hour ago. */
function eventsToday(events: AgendaEvent[], now: string): AgendaEvent[] {
  const today = localDay(now);
  const nowMs = Date.parse(now);
  return events.filter((e) =>
    e.all_day ? e.when.slice(0, 10) === today : localDay(e.when) === today && Date.parse(e.when) >= nowMs - 3_600_000,
  );
}

function count(n: number, one: string, many: string, none: string): string {
  return n === 0 ? none : `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

function Greeting({ data, briefing, onNavigate }: { data: HomeResponse; briefing: Briefing; onNavigate: (v: View) => void }) {
  const today = localDay(data.now);
  const open = data.tasks.actionable.filter((t) => t.action === null);
  const due = open.filter((t) => (daysLeft(t, today) ?? 1) <= 0).length;
  const overdue = open.filter((t) => (daysLeft(t, today) ?? 0) < 0).length;
  const events = briefing.data ? eventsToday(briefing.data.agenda.events, data.now).length : null;
  const drafts = data.drafts.awaiting;

  const strong = (text: string, view?: View) =>
    view ? (
      <button onClick={() => onNavigate(view)} className="font-medium text-ink underline decoration-line-strong underline-offset-4 hover:decoration-accent">
        {text}
      </button>
    ) : (
      <span className="font-medium text-ink">{text}</span>
    );

  return (
    <header className="mb-9 max-w-3xl">
      <p className="smallcaps">{longDay(data.now)}</p>
      <h1 className="title-1 mt-2">
        {greeting(data.now)}
        {data.name ? `, ${data.name}` : ""}.
      </h1>
      <p className="lede mt-3">
        {events === null ? (
          <span className="skeleton inline-block h-4 w-80 max-w-full align-middle" aria-hidden="true" />
        ) : (
          <>
            You have {strong(count(events, "event", "events", "no events"))} today,{" "}
            {strong(count(due, overdue ? "task due or overdue" : "task due", overdue ? "tasks due or overdue" : "tasks due", "nothing due"), due ? "tasks" : undefined)}{" "}
            and {strong(count(drafts, "draft", "drafts", "no drafts"), drafts ? "drafts" : undefined)} waiting for review.
          </>
        )}
      </p>
      <p className="mt-1.5 text-sm text-muted" title={data.since ? formatDateTime(data.since) : undefined}>
        {data.since ? (
          <>
            Since you were last here, <span className="num">{timeAgo(data.since, data.now)}</span>:{" "}
            <span className="num">{data.feed.newCount}</span> new in the feed.
          </>
        ) : (
          "Here is where things stand."
        )}
      </p>
      <NowNote />
    </header>
  );
}

// ── Needs you ───────────────────────────────────────────────────────────────

function eventTime(e: AgendaEvent): string {
  if (e.all_day) return "All day";
  return new Date(e.when).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

function Agenda({ briefing, now }: { briefing: Briefing; now: string }) {
  if (briefing.error) return <Meta>Couldn&apos;t load the calendar.</Meta>;
  if (!briefing.data) {
    return (
      <div className="space-y-2.5">
        <Bone className="h-12 w-full rounded-xl" />
        <Bone className="h-12 w-full rounded-xl" />
      </div>
    );
  }
  const { agenda } = briefing.data;
  if (!agenda.exists) return <QuietLine command="proxenos clone recall">No agenda yet. This reads your calendars:</QuietLine>;
  const today = eventsToday(agenda.events, now);
  const nowMs = Date.parse(now);
  const next = today.length === 0 ? agenda.events.find((e) => Date.parse(e.when) > nowMs) : undefined;
  return (
    <div className="space-y-2.5">
      {today.length === 0 ? (
        <Meta>
          Nothing else on the calendar today.
          {next && (
            <>
              {" "}
              Next: <span className="text-ink">{next.title}</span>, <span className="num">{formatDateTime(next.when)}</span>.
            </>
          )}
        </Meta>
      ) : (
        <ol className="space-y-2">
          {today.map((e) => {
            const past = !e.all_day && Date.parse(e.when) < nowMs;
            return (
              <li key={`${e.when}:${e.title}`} className={cn("tile flex items-start gap-3 px-3 py-2.5", past && "opacity-60")}>
                <span className="num w-[4.25rem] flex-shrink-0 pt-px text-sm text-accent">{eventTime(e)}</span>
                <span className="min-w-0 flex-1 break-words text-sm leading-snug text-ink">{e.title}</span>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

function TodayCard({ home, data, briefing, onNavigate }: { home: HomeState; data: HomeResponse; briefing: Briefing; onNavigate: (v: View) => void }) {
  const open = data.tasks.actionable.filter((t) => t.action === null);
  const today = localDay(data.now);
  const urgent = open.filter((t) => isUrgent(t, today)).length;
  const top = byUrgency(open, data.now).slice(0, 4);
  return (
    <Card
      icon={ListTodo}
      kicker="Today"
      title="Agenda and tasks"
      link="All tasks"
      onLink={() => onNavigate("tasks")}
      tier="priority"
      className="md:col-span-2 lg:col-span-6 xl:col-span-8"
    >
      <div className="grid gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div className="min-w-0">
          <p className="smallcaps mb-2.5 flex items-center gap-1.5">
            <CalendarDays size={13} aria-hidden="true" /> Calendar
          </p>
          <Agenda briefing={briefing} now={data.now} />
        </div>
        <div className="min-w-0">
          <p className="smallcaps mb-2.5 flex items-center gap-1.5">
            <ListTodo size={13} aria-hidden="true" /> On your plate
            {data.tasks.exists && (
              <span className="ml-auto text-xs font-normal tracking-normal text-muted [font-variant-caps:normal]">
                <span className="num">{open.length}</span> open
              </span>
            )}
          </p>
          {!data.tasks.exists ? (
            <QuietLine command="proxenos clone tasks">No task list yet. This builds it from your messages:</QuietLine>
          ) : (
            <>
              <Meta className="mb-2">
                {urgent > 0 ? (
                  <>
                    <span className="num text-warn-ink">{urgent}</span> overdue or due soon
                  </>
                ) : (
                  "Nothing overdue"
                )}
                {data.tasks.waiting > 0 && (
                  <>
                    {" "}
                    · <span className="num">{data.tasks.waiting}</span> waiting on others
                  </>
                )}
              </Meta>
              {top.length > 0 ? (
                <ul className="tile divide-y divide-line overflow-hidden">
                  {top.map((t) => (
                    <TaskRow key={t.id} task={t} now={data.now} actions={["done", "not_mine"]} onAct={home.actTask} showEvidence={false} />
                  ))}
                </ul>
              ) : (
                <Meta>Nothing open.</Meta>
              )}
            </>
          )}
        </div>
      </div>
    </Card>
  );
}

/** The start of a draft's text with the markdown marks taken off, for a preview line. */
function preview(body: string): string {
  return body
    .replace(/^\s*#{1,6}[^\n]*\n+/, "") // a leading heading repeats the title
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/^[#>\-*+\d.)\s]+/gm, "")
    .replace(/[*_`]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 180);
}

function DraftRow({ draft, onOpen }: { draft: Draft; onOpen: () => void }) {
  return (
    <li>
      <button onClick={onOpen} className="tile tile-hover block w-full px-3.5 py-3 text-left">
        <span className="flex flex-wrap items-center gap-1.5">
          <KindBadge kind={draft.kind} />
          <ChannelBadge channel={draft.channel} />
        </span>
        <span className="title-3 mt-1.5 block break-words">{draft.title}</span>
        {draft.to && <span className="block text-xs text-muted">To {draft.to}</span>}
        {draft.body && <span className="mt-1 line-clamp-2 break-words text-sm leading-relaxed text-muted">{preview(draft.body)}</span>}
      </button>
    </li>
  );
}

function DraftsCard({ data, briefing, onNavigate }: { data: HomeResponse; briefing: Briefing; onNavigate: (v: View) => void }) {
  const d = data.drafts;
  const reviews = briefing.data?.reviews;
  return (
    <Card
      icon={PenLine}
      kicker="Waiting for you"
      title="Drafts to approve"
      count={d.exists ? d.awaiting : undefined}
      link="Review"
      onLink={() => onNavigate("drafts")}
      tier="priority"
      className="md:col-span-2 lg:col-span-6 xl:col-span-4"
    >
      {reviews && reviews.reviewed > 0 ? (
        <ReviewBar reviews={reviews} />
      ) : reviews ? (
        <Meta>
          Written as you, never sent. Approve, edit or discard them in Drafts; each choice is logged, and once
          eight in ten are approved a channel can move on to acting.
        </Meta>
      ) : null}
      {d.top.length === 0 ? (
        d.exists ? (
          <Meta>Nothing is waiting for your approval.</Meta>
        ) : (
          <QuietLine command="proxenos clone work">No drafts yet. This writes them from your tasks and ideas:</QuietLine>
        )
      ) : (
        <ul className="space-y-2">
          {d.top.map((x) => (
            <DraftRow key={x.id} draft={x} onOpen={() => onNavigate("drafts")} />
          ))}
        </ul>
      )}
    </Card>
  );
}

// ── Brought to mind ─────────────────────────────────────────────────────────

const RECALL_KIND: Record<RecallKind, { label: string; icon: LucideIcon }> = {
  event: { label: "Coming up", icon: CalendarDays },
  task: { label: "Task", icon: ListTodo },
  feed: { label: "In your feed", icon: Rss },
  person: { label: "Person", icon: UserRound },
};
const RECALL_SHOWN = 6;
const MEMORIES_SHOWN = 2;

/** Up to six triggers, a kind at a time (event, task, person, feed, then the next of each), shown by kind. */
function pickTriggers(all: RecallTrigger[]): RecallTrigger[] {
  const order: RecallKind[] = ["event", "task", "person", "feed"];
  const lists = order.map((k) => all.filter((t) => t.kind === k));
  const picked: RecallTrigger[] = [];
  for (let round = 0; picked.length < RECALL_SHOWN && round < RECALL_SHOWN; round++) {
    for (const list of lists) if (list[round] && picked.length < RECALL_SHOWN) picked.push(list[round]);
  }
  return picked.sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind));
}

function whenLine(t: RecallTrigger, now: string): string {
  if (!t.when) return "";
  if (t.kind === "event") return formatDateTime(t.when);
  if (t.kind === "task") return `due ${shortDate(t.when, now)}`;
  if (t.kind === "person") return `last seen ${shortDate(t.when, now)}`;
  return shortDate(t.when, now);
}

function RecallBlock({ t, now, onMemory }: { t: RecallTrigger; now: string; onMemory: HomeProps["onMemory"] }) {
  const { label, icon: Icon } = RECALL_KIND[t.kind];
  const when = whenLine(t, now);
  return (
    <li className="tile min-w-0 p-3.5">
      <div className="flex min-w-0 items-center gap-1.5 text-xs text-muted">
        <Icon size={13} className="flex-shrink-0 text-accent" aria-hidden="true" />
        <span className="smallcaps flex-shrink-0 text-[0.75rem]">{label}</span>
        {when && <span className="num truncate">{when}</span>}
      </div>
      <h4 className="title-3 mt-1 break-words">{t.title}</h4>
      <ul className="mt-2 space-y-1">
        {t.memories.slice(0, MEMORIES_SHOWN).map((m) => (
          <li key={m.id}>
            <button
              onClick={() => onMemory("", m.id)}
              className="-mx-1.5 block w-[calc(100%+0.75rem)] rounded-lg px-1.5 py-1.5 text-left transition-colors hover:bg-surface-2"
            >
              <span className="flex min-w-0 items-center gap-2 text-xs text-muted">
                <SourceBadge kind={m.source} />
                <span className="min-w-0 flex-1 truncate">{whoWhere(m)}</span>
                <span className="num flex-shrink-0">{shortDate(m.ts, now)}</span>
              </span>
              {plain(m.snippet).trim() && (
                <span className="mt-1 line-clamp-2 break-words text-sm leading-relaxed text-ink/85">
                  <Marked text={m.snippet} />
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </li>
  );
}

function RecallCard({ now, onNavigate, onMemory }: { now: string } & Pick<HomeProps, "onNavigate" | "onMemory">) {
  const { data, error } = useJson<RecallResponse>("/api/recall");
  const picked = data ? pickTriggers(data.triggers) : [];
  return (
    <Card
      icon={Brain}
      kicker="From your past"
      title="Memories for today"
      count={data?.exists ? data.triggers.length : undefined}
      link="Search memory"
      onLink={() => onNavigate("memory")}
      className="md:col-span-2 lg:col-span-6 xl:col-span-12"
    >
      {error ? (
        <Meta>Couldn&apos;t load today&apos;s memories.</Meta>
      ) : !data ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Bone key={i} className="h-36 rounded-xl" />
          ))}
        </div>
      ) : !data.exists ? (
        <QuietLine command="proxenos clone recall">No memories for today yet. This looks through your past:</QuietLine>
      ) : picked.length === 0 ? (
        <Meta>Nothing in your past stood out for today&apos;s events, tasks or reading.</Meta>
      ) : (
        <>
          <Meta>
            What your messages, mail and notes say about what is coming up
            {data.generated && (
              <span title={formatDateTime(data.generated)}>
                {" "}
                · updated <span className="num">{timeAgo(data.generated, data.now)}</span>
              </span>
            )}
          </Meta>
          {/* On a phone, the first three; the rest are a tap away in Memory. */}
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 max-sm:[&>li:nth-child(n+4)]:hidden">
            {picked.map((t) => (
              <RecallBlock key={`${t.kind}:${t.id}`} t={t} now={now} onMemory={onMemory} />
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

// ── Your data ───────────────────────────────────────────────────────────────

const ACTIVITY_ROWS = 6;

function ActivityCard({ briefing, onNavigate }: { briefing: Briefing; onNavigate: (v: View) => void }) {
  const a = briefing.data?.activity;
  const rows = a ? a.series.slice(0, ACTIVITY_ROWS) : [];
  const total = a ? a.series.reduce((sum, s) => sum + s.total, 0) : 0;
  const daily = a ? a.days.map((_, i) => a.series.reduce((sum, s) => sum + s.counts[i], 0)) : [];
  const peak = daily.length ? daily.indexOf(Math.max(...daily)) : -1;
  return (
    <Card
      icon={TrendingUp}
      kicker="Last 30 days"
      title="Activity by source"
      link="Memory"
      onLink={() => onNavigate("memory")}
      className="md:col-span-2 lg:col-span-4 xl:col-span-7"
    >
      {briefing.error ? (
        <Meta>Couldn&apos;t load activity.</Meta>
      ) : !a ? (
        <div className="space-y-4">
          {[0, 1, 2, 3].map((i) => (
            <Bone key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : !a.indexed ? (
        <QuietLine command="proxenos index">No memory index yet. This builds it from everything synced:</QuietLine>
      ) : rows.length === 0 ? (
        <Meta>Nothing new came in over the last 30 days.</Meta>
      ) : (
        <>
          <Meta>
            <span className="num text-ink">{total.toLocaleString()}</span> messages, mails and other records across{" "}
            <span className="num text-ink">{a.series.length}</span> sources
            {peak >= 0 && daily[peak] > 0 && (
              <>
                ; the busiest day was <span className="num text-ink">{shortDate(a.days[peak])}</span> with{" "}
                <span className="num">{daily[peak].toLocaleString()}</span>
              </>
            )}
            . Each line has its own scale.
          </Meta>
          <ul className="space-y-1">
            {rows.map((s) => {
              const meta = sourceMeta(s.source);
              const top = Math.max(...s.counts);
              return (
                <li key={s.source} className="grid grid-cols-[minmax(0,7rem)_minmax(0,1fr)_3.25rem] items-center gap-3 py-1.5 sm:grid-cols-[9.5rem_minmax(0,1fr)_4.5rem]">
                  <span className="flex min-w-0 items-center gap-2 text-sm text-ink/90">
                    <SourceChip kind={s.source} size={24} />
                    <span className="truncate">{meta.label}</span>
                  </span>
                  <Sparkline
                    values={s.counts}
                    days={a.days}
                    color={meta.color}
                    label={`${meta.label}: ${s.total.toLocaleString()} records in 30 days, at most ${top.toLocaleString()} in a day`}
                  />
                  <span className="num text-right text-sm text-ink">{s.total.toLocaleString()}</span>
                </li>
              );
            })}
          </ul>
          {a.series.length > rows.length && (
            <Meta className="text-xs">
              And {joinAnd(a.series.slice(rows.length).map((s) => sourceMeta(s.source).label))}.
            </Meta>
          )}
          <table className="sr-only">
            <caption>Records per source over the last 30 days</caption>
            <thead>
              <tr>
                <th scope="col">Source</th>
                <th scope="col">Total</th>
                <th scope="col">Busiest day</th>
              </tr>
            </thead>
            <tbody>
              {a.series.map((s) => {
                const i = s.counts.indexOf(Math.max(...s.counts));
                return (
                  <tr key={s.source}>
                    <th scope="row">{sourceMeta(s.source).label}</th>
                    <td>{s.total}</td>
                    <td>
                      {shortDate(a.days[i])}: {s.counts[i]}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </Card>
  );
}

const FRESH_SHOWN = 8;
const FRESH_SPAN_HOURS = 24 * 30; // a source a month behind shows an empty meter

/** How much of the meter to fill: full when just synced, falling on a log scale to empty at a month. */
function freshFill(lastSync: string | null, now: string): number {
  const h = hoursSince(lastSync, now);
  if (!Number.isFinite(h)) return 0;
  return Math.max(0.04, 1 - Math.log1p(Math.max(0, h)) / Math.log1p(FRESH_SPAN_HOURS));
}

function FreshnessCard({ data, onNavigate }: { data: HomeResponse; onNavigate: (v: View) => void }) {
  const sources = [...data.sources].sort((a, b) => (Date.parse(b.lastSync ?? "") || 0) - (Date.parse(a.lastSync ?? "") || 0));
  const states = sources.map((s) => freshness(s.lastSync, data.now).label);
  const fresh = states.filter((l) => l === "Fresh").length;
  const stale = states.filter((l) => l === "Stale").length;
  return (
    <Card
      icon={Radar}
      kicker="Sync"
      title="Source freshness"
      link="Status"
      onLink={() => onNavigate("status")}
      className="md:col-span-2 lg:col-span-2 xl:col-span-5"
    >
      {sources.some((s) => s.lastSync) ? (
        <>
          <Meta>
            <span className="num text-ok-ink">{fresh}</span> of <span className="num">{sources.length}</span> synced in the last 6 hours
            {stale > 0 && (
              <>
                , <span className="num text-bad-ink">{stale}</span> over 3 days behind
              </>
            )}
            .
          </Meta>
          <ul className="space-y-2.5">
            {sources.slice(0, FRESH_SHOWN).map((s) => {
              const f = freshness(s.lastSync, data.now);
              const fill = freshFill(s.lastSync, data.now);
              return (
                <li key={s.kind} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1" title={s.lastSync ? formatDateTime(s.lastSync) : "Not synced yet"}>
                  <span className="flex min-w-0 items-center gap-2 text-sm text-ink/90">
                    <SourceIcon kind={s.kind} size={14} />
                    <span className="truncate">{sourceMeta(s.kind).label}</span>
                  </span>
                  <span className={cn("num whitespace-nowrap text-right text-xs", f.text)}>
                    {f.label} · {s.lastSync ? timeAgo(s.lastSync, data.now) : "never"}
                  </span>
                  <span className="col-span-2 block h-1.5 overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
                    <span className={cn("block h-full rounded-full", f.dot)} style={{ width: `${fill * 100}%` }} />
                  </span>
                </li>
              );
            })}
          </ul>
          {sources.length > FRESH_SHOWN && (
            <Meta className="text-xs">And {sources.length - FRESH_SHOWN} more on the Status page.</Meta>
          )}
        </>
      ) : (
        <QuietLine command="proxenos sync">Nothing synced yet. This pulls every source:</QuietLine>
      )}
    </Card>
  );
}

// ── Reading and ideas ───────────────────────────────────────────────────────

function Pick({ item }: { item: FeedItem }) {
  const open = (it: FeedItem) =>
    sendFeedback(it.id, "open").catch(() => {
      // Opening still works; only the log line is lost.
    });
  return (
    <li className="tile tile-hover px-4 py-3">
      <div className="flex min-w-0 items-center gap-2 text-xs text-muted">
        <span className="truncate">{sourceLabel(item.source)}</span>
        <span className="smallcaps text-[0.72rem]">{item.kind}</span>
        <span className="num ml-auto text-accent" title="Match with your profile">
          {percent(item.score)}%
        </span>
      </div>
      <h4 className="title-3 mt-1 break-words">
        <TitleLink item={item} onOpen={open} />
      </h4>
      {item.why && <p className="mt-1 line-clamp-2 break-words text-sm leading-relaxed text-muted">{item.why}</p>}
    </li>
  );
}

function FeedCard({ data, onNavigate }: { data: HomeResponse; onNavigate: (v: View) => void }) {
  const { newCount, top, latest } = data.feed;
  return (
    <Card icon={Rss} kicker="Reading" title="Feed picks" link="Feed" onLink={() => onNavigate("feed")} className="md:col-span-1 lg:col-span-3 xl:col-span-5">
      {!latest ? (
        <QuietLine command="proxenos clone tracker">No feed yet. The tracker fills it:</QuietLine>
      ) : (
        <>
          <Meta>
            {data.since ? (
              newCount > 0 ? (
                <>
                  <span className="num text-ink">{newCount}</span> new {newCount === 1 ? "item" : "items"} since you were here. Top 3:
                </>
              ) : (
                <>
                  Nothing new since then. The latest batch came in <span className="num">{timeAgo(latest.ts, data.now)}</span>.
                </>
              )
            ) : (
              <>
                <span className="num text-ink">{newCount}</span> {newCount === 1 ? "item" : "items"} in the latest batch,{" "}
                <span className="num">{timeAgo(latest.ts, data.now)}</span>. Top 3:
              </>
            )}
          </Meta>
          {top.length > 0 && (
            <ol className="space-y-2">
              {top.map((it) => (
                <Pick key={it.id} item={it} />
              ))}
            </ol>
          )}
        </>
      )}
    </Card>
  );
}

function AdviceCard({ home, data, onNavigate }: { home: HomeState; data: HomeResponse; onNavigate: (v: View) => void }) {
  const a = data.advice;
  return (
    <Card
      icon={Lightbulb}
      kicker="Advice"
      title="Newest suggestion"
      count={a.exists ? `${a.unanswered} open` : undefined}
      link="Advice"
      onLink={() => onNavigate("advice")}
      className="md:col-span-1 lg:col-span-3 xl:col-span-4"
    >
      {!a.exists ? (
        <QuietLine command="proxenos clone advisor">No advice yet. Once the profile exists, this writes some:</QuietLine>
      ) : !a.pick ? (
        <Meta>The newest advice file has no suggestions.</Meta>
      ) : (
        <>
          <Meta>
            <span className="num text-ink">{a.unanswered}</span> of <span className="num">{a.total}</span> not answered, from{" "}
            <span className="num">{shortDate(a.date, data.now)}</span>.
          </Meta>
          <SuggestionCard s={a.pick} now={data.now} actions={["useful", "not_me"]} onReact={home.reactAdvice} compact />
        </>
      )}
    </Card>
  );
}

function NetworkCard({ data, onNavigate }: { data: HomeResponse; onNavigate: (v: View) => void }) {
  const n = data.network;
  return (
    <Card icon={NetworkIcon} kicker="People" title="Network" link="Graph" onLink={() => onNavigate("network")} className="md:col-span-2 lg:col-span-6 xl:col-span-3">
      {n.exists ? (
        <>
          <NetworkThumb onOpen={() => onNavigate("network")} />
          {n.outreach && (
            <p className="break-words text-sm leading-relaxed text-muted">
              Reach out to <span className="text-ink">{n.outreach.name}</span>
              {n.outreach.ask && <>: {n.outreach.ask}</>}
            </p>
          )}
        </>
      ) : (
        <QuietLine command="proxenos clone network --people-only">No people index yet:</QuietLine>
      )}
    </Card>
  );
}

function ProfileCard({ data, onNavigate }: { data: HomeResponse; onNavigate: (v: View) => void }) {
  const s = data.self;
  const latest = s.latest;
  return (
    <Card
      icon={UserRound}
      kicker="Self-model"
      title="Your profile"
      link="Profile"
      onLink={() => onNavigate("profile")}
      tier="quiet"
      className="md:col-span-2 lg:col-span-6 xl:col-span-12"
    >
      {!s.exists ? (
        <QuietLine command="proxenos master">No profile yet. This builds it:</QuietLine>
      ) : (
        <>
          <Meta>
            Last changed{" "}
            <span className="num text-ink" title={formatDateTime(s.updated)}>
              {latest ? shortDate(latest.date, data.now) : timeAgo(s.updated, data.now)}
            </span>
            {latest ? ". From the changelog:" : ". The changelog has no dated entries yet."}
          </Meta>
          {latest && latest.body && (
            <div className="max-h-56 overflow-y-auto border-l-2 border-accent/40 pl-4">
              <Markdown source={latest.body} compact />
            </div>
          )}
        </>
      )}
    </Card>
  );
}

// ── Care ────────────────────────────────────────────────────────────────────

/** Where health care stands, in a sentence, and the one item that most needs doing. */
function CareCard({ onNavigate }: { onNavigate: (v: View) => void }) {
  const { data, error } = useJson<CareResponse>("/api/care");
  const urgent = data ? mostUrgent(data.items) : null;
  const moves = data ? yourMoves(data.items) : 0;
  const others = data ? data.items.filter((i) => careStatus(i) !== null && careStatus(i) !== "done").length - moves : 0;
  const due = data && urgent ? careDue(urgent, data.now) : null;
  const yours = urgent !== null && urgent.waiting_on === "me" && careStatus(urgent) === "open";
  return (
    <Card
      icon={HeartPulse}
      kicker="Health care"
      title="Care"
      link="Open care"
      onLink={() => onNavigate("care")}
      tier={moves > 0 ? "priority" : "default"}
      className="md:col-span-2 lg:col-span-6 xl:col-span-12"
    >
      {error ? (
        <Meta>Couldn&apos;t load care.</Meta>
      ) : !data ? (
        <Bone className="h-16 rounded-xl" />
      ) : !data.exists ? (
        <QuietLine command="proxenos clone care">Nothing on your care yet. This reads your health-care admin:</QuietLine>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:items-start">
          <div className="min-w-0">
            <p className="text-[1.0625rem] leading-relaxed text-ink">
              {firstSentence(data.summary) || "Nothing about health care turned up in your recent records."}
            </p>
            {moves + others > 0 && (
              <Meta className="mt-2">
                <span className="num">{moves}</span> for you to do · <span className="num">{others}</span> waiting on
                others
              </Meta>
            )}
          </div>
          {urgent ? (
            <button onClick={() => onNavigate("care")} className="tile tile-hover block w-full px-3.5 py-3 text-left">
              <span className={cn("smallcaps text-[0.75rem]", yours && "text-accent")}>
                {yours ? "Your next step" : "Waiting on others"}
              </span>
              <span className="title-3 mt-1 block break-words">{urgent.title}</span>
              {urgent.next_step && (
                <span className="mt-1 line-clamp-2 block break-words text-sm leading-relaxed text-muted">{urgent.next_step}</span>
              )}
              {due && (
                <span className={cn("num mt-1.5 block text-xs", due.tone === "bad" ? "text-bad-ink" : due.tone === "warn" ? "text-warn-ink" : "text-muted")}>
                  {due.text}
                </span>
              )}
            </button>
          ) : (
            <Meta>Nothing open.</Meta>
          )}
        </div>
      )}
    </Card>
  );
}

// ── The briefing ────────────────────────────────────────────────────────────

export function Home({ home, onNavigate, onMemory }: HomeProps) {
  const { data, error, clearError } = home;
  const briefing = useJson<BriefingResponse>("/api/briefing");

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load the brief: ${error}`} /> : <HomeSkeleton />;
  }

  if (!data.vault.exists) return <NoVault path={data.vault.path} />;

  return (
    <div className="mx-auto w-full max-w-[1500px] px-4 pb-28 pt-7 sm:px-6 md:pb-14 lg:px-8">
      {error && <ErrorBanner message={error} onDismiss={clearError} />}
      <Greeting data={data} briefing={briefing} onNavigate={onNavigate} />

      <Section id="home-needs-you" label="Needs you">
        <TodayCard home={home} data={data} briefing={briefing} onNavigate={onNavigate} />
        <DraftsCard data={data} briefing={briefing} onNavigate={onNavigate} />
        <CareCard onNavigate={onNavigate} />
      </Section>

      <Section id="home-past" label="Brought to mind">
        <RecallCard now={data.now} onNavigate={onNavigate} onMemory={onMemory} />
      </Section>

      <Section id="home-data" label="Your data">
        <ActivityCard briefing={briefing} onNavigate={onNavigate} />
        <FreshnessCard data={data} onNavigate={onNavigate} />
      </Section>

      <Section id="home-ideas" label="Reading, people and profile">
        <FeedCard data={data} onNavigate={onNavigate} />
        <AdviceCard home={home} data={data} onNavigate={onNavigate} />
        <NetworkCard data={data} onNavigate={onNavigate} />
        <ProfileCard data={data} onNavigate={onNavigate} />
      </Section>
    </div>
  );
}
