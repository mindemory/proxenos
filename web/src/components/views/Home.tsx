"use client";

import { ArrowRight, type LucideIcon, Lightbulb, ListTodo, Network as NetworkIcon, PenLine, Radar, Rss, UserRound } from "lucide-react";

import { SuggestionCard } from "@/components/advice/SuggestionCard";
import { ChannelBadge, KindBadge } from "@/components/drafts/badges";
import { ErrorBanner, LoadingRows, NoVault, QuietLine } from "@/components/EmptyState";
import { TitleLink } from "@/components/feed/ItemCard";
import type { View } from "@/components/layout/nav";
import { Markdown } from "@/components/Markdown";
import { NetworkThumb } from "@/components/network/NetworkThumb";
import { SourceIcon } from "@/components/SourceBadge";
import { TaskRow } from "@/components/tasks/TaskRow";
import { sendFeedback, type useHome } from "@/lib/client";
import {
  formatDateTime,
  freshness,
  greeting,
  localDay,
  percent,
  shortDate,
  sourceLabel,
  timeAgo,
} from "@/lib/format";
import { byUrgency, isUrgent } from "@/lib/tasks";
import type { Draft, FeedItem, HomeResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

type HomeState = ReturnType<typeof useHome>;

interface HomeProps {
  home: HomeState;
  onNavigate: (view: View) => void;
}

/** One card of the briefing grid: a title, a link to the full view, and a little content. */
function Card({
  icon: Icon,
  title,
  count,
  link,
  onLink,
  className,
  children,
}: {
  icon: LucideIcon;
  title: string;
  count?: string | number;
  link: string;
  onLink: () => void;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={cn("flex min-w-0 flex-col rounded-2xl border border-line bg-surface p-4 sm:p-5", className)}>
      <div className="mb-3 flex items-center gap-2.5">
        <Icon size={17} className="flex-shrink-0 text-accent" />
        <h2 className="font-display text-xl text-ink">{title}</h2>
        {count !== undefined && <span className="num text-sm text-muted">{count}</span>}
        <button
          onClick={onLink}
          className="ml-auto inline-flex items-center gap-1 whitespace-nowrap rounded text-sm text-accent underline-offset-4 hover:underline"
        >
          {link}
          <ArrowRight size={14} />
        </button>
      </div>
      <div className="flex-1 space-y-3">{children}</div>
    </section>
  );
}

function Meta({ children }: { children: React.ReactNode }) {
  return <p className="text-sm leading-relaxed text-muted">{children}</p>;
}

// ── Cards ───────────────────────────────────────────────────────────────────

function TasksCard({ home, data, onNavigate }: { home: HomeState; data: HomeResponse; onNavigate: (v: View) => void }) {
  const open = data.tasks.actionable.filter((t) => t.action === null);
  const urgent = open.filter((t) => isUrgent(t, localDay(data.now))).length;
  const top = byUrgency(open, data.now).slice(0, 4);
  return (
    <Card
      icon={ListTodo}
      title="Today's tasks"
      count={data.tasks.exists ? open.length : undefined}
      link="All tasks"
      onLink={() => onNavigate("tasks")}
      className="lg:col-span-3 xl:col-span-5"
    >
      {!data.tasks.exists ? (
        <QuietLine command="twin clone tasks">No task list yet. This builds it from your messages:</QuietLine>
      ) : (
        <>
          <Meta>
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
            {data.tasks.generated && (
              <span title={formatDateTime(data.tasks.generated)}>
                {" "}
                · updated <span className="num">{timeAgo(data.tasks.generated, data.now)}</span>
              </span>
            )}
          </Meta>
          {top.length > 0 ? (
            <ul className="-mx-4 divide-y divide-line border-y border-line sm:-mx-5">
              {top.map((t) => (
                <TaskRow
                  key={t.id}
                  task={t}
                  now={data.now}
                  actions={["done", "not_mine"]}
                  onAct={home.actTask}
                  showEvidence={false}
                />
              ))}
            </ul>
          ) : (
            <Meta>Nothing open.</Meta>
          )}
        </>
      )}
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
      <button onClick={onOpen} className="block w-full rounded-xl border border-line bg-bg/40 px-3.5 py-3 text-left transition-colors hover:border-line-strong hover:bg-surface-2">
        <span className="flex flex-wrap items-center gap-1.5">
          <KindBadge kind={draft.kind} />
          <ChannelBadge channel={draft.channel} />
        </span>
        <span className="mt-1.5 block break-words font-display text-lg leading-snug text-ink">{draft.title}</span>
        {draft.to && <span className="block text-xs text-muted">To {draft.to}</span>}
        {draft.body && <span className="mt-1 block line-clamp-2 break-words text-sm leading-relaxed text-muted">{preview(draft.body)}</span>}
      </button>
    </li>
  );
}

function DraftsCard({ data, onNavigate }: { data: HomeResponse; onNavigate: (v: View) => void }) {
  const d = data.drafts;
  return (
    <Card
      icon={PenLine}
      title="Drafts to approve"
      count={d.exists ? d.awaiting : undefined}
      link="Review drafts"
      onLink={() => onNavigate("drafts")}
      className="lg:col-span-3 xl:col-span-4"
    >
      {d.top.length === 0 ? (
        d.exists ? (
          <Meta>Nothing is waiting for your approval.</Meta>
        ) : (
          <QuietLine command="twin clone work">No drafts yet. This writes them from your tasks and ideas:</QuietLine>
        )
      ) : (
        <>
          <Meta>
            Written as you, never sent. {d.awaiting > d.top.length && <>The newest {d.top.length} of <span className="num">{d.awaiting}</span>:</>}
          </Meta>
          <ul className="space-y-2">
            {d.top.map((x) => (
              <DraftRow key={x.id} draft={x} onOpen={() => onNavigate("drafts")} />
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

function Pick({ item }: { item: FeedItem }) {
  const open = (it: FeedItem) =>
    sendFeedback(it.id, "open").catch(() => {
      // Opening still works; only the log line is lost.
    });
  return (
    <li className="rounded-xl border border-line bg-bg/40 px-4 py-3">
      <div className="flex min-w-0 items-center gap-2 text-xs text-muted">
        <span className="truncate">{sourceLabel(item.source)}</span>
        <span className="eyebrow">{item.kind}</span>
        <span className="num ml-auto text-accent" title="Match with your profile">
          {percent(item.score)}%
        </span>
      </div>
      <h3 className="mt-1 break-words font-display text-lg leading-snug text-ink">
        <TitleLink item={item} onOpen={open} />
      </h3>
      {item.why && <p className="mt-1 line-clamp-2 break-words text-sm leading-relaxed text-muted">{item.why}</p>}
    </li>
  );
}

function FeedCard({ data, onNavigate }: { data: HomeResponse; onNavigate: (v: View) => void }) {
  const { newCount, top, latest } = data.feed;
  return (
    <Card icon={Rss} title="Feed picks" link="Open feed" onLink={() => onNavigate("feed")} className="lg:col-span-4 xl:col-span-5">
      {!latest ? (
        <QuietLine command="twin clone tracker">No feed yet. The tracker fills it:</QuietLine>
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
      title="Newest advice"
      count={a.exists ? a.total : undefined}
      link="All advice"
      onLink={() => onNavigate("advice")}
      className="lg:col-span-3 xl:col-span-4"
    >
      {!a.exists ? (
        <QuietLine command="twin clone advisor">No advice yet. Once the profile exists, this writes some:</QuietLine>
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
    <Card icon={NetworkIcon} title="Network" link="Open graph" onLink={() => onNavigate("network")} className="lg:col-span-2 xl:col-span-3">
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
        <QuietLine command="twin clone network --people-only">No people index yet:</QuietLine>
      )}
    </Card>
  );
}

function FreshnessCard({ data, onNavigate }: { data: HomeResponse; onNavigate: (v: View) => void }) {
  const sources = [...data.sources].sort((a, b) => (Date.parse(b.lastSync ?? "") || 0) - (Date.parse(a.lastSync ?? "") || 0));
  const SHOWN = 9;
  return (
    <Card icon={Radar} title="Sources" link="Sync status" onLink={() => onNavigate("status")} className="lg:col-span-3 xl:col-span-3">
      {sources.some((s) => s.lastSync) ? (
        <ul className="space-y-1.5">
          {sources.slice(0, SHOWN).map((s) => {
            const f = freshness(s.lastSync, data.now);
            return (
              <li key={s.kind} className="flex items-center gap-2.5 text-sm" title={s.lastSync ? formatDateTime(s.lastSync) : "Not synced yet"}>
                <span className={cn("h-2 w-2 flex-shrink-0 rounded-full", f.dot)} aria-hidden="true" />
                <SourceIcon kind={s.kind} size={14} />
                <span className="min-w-0 flex-1 truncate text-ink/90">{sourceLabel(s.kind)}</span>
                <span className={cn("num whitespace-nowrap text-xs", f.text)}>{s.lastSync ? timeAgo(s.lastSync, data.now) : "never"}</span>
              </li>
            );
          })}
          {sources.length > SHOWN && <li className="text-xs text-muted">and {sources.length - SHOWN} more</li>}
        </ul>
      ) : (
        <QuietLine command="twin sync">Nothing synced yet. This pulls every source:</QuietLine>
      )}
    </Card>
  );
}

function ProfileCard({ data, onNavigate }: { data: HomeResponse; onNavigate: (v: View) => void }) {
  const s = data.self;
  const latest = s.latest;
  return (
    <Card icon={UserRound} title="Your profile" link="Open profile" onLink={() => onNavigate("twin")} className="md:col-span-2 lg:col-span-6 xl:col-span-12">
      {!s.exists ? (
        <QuietLine command="twin master">No profile yet. This builds it:</QuietLine>
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

export function Home({ home, onNavigate }: HomeProps) {
  const { data, error, clearError } = home;

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load the brief: ${error}`} /> : <LoadingRows />;
  }

  if (!data.vault.exists) return <NoVault path={data.vault.path} />;

  return (
    <div className="mx-auto w-full max-w-[1500px] px-4 pb-28 pt-5 sm:px-6 md:pb-12 lg:px-8">
      {error && <ErrorBanner message={error} onDismiss={clearError} />}
      <div className="mb-5">
        <h1 className="font-display text-3xl leading-tight tracking-tight text-ink sm:hidden">
          {greeting(data.now)}
          {data.name ? `, ${data.name}` : ""}.
        </h1>
        <p className="mt-1 text-muted sm:mt-0" title={data.since ? formatDateTime(data.since) : undefined}>
          {data.since ? (
            <>
              Since you were last here, <span className="num">{timeAgo(data.since, data.now)}</span>.
            </>
          ) : (
            "Here is where things stand."
          )}
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-6 xl:grid-cols-12">
        <TasksCard home={home} data={data} onNavigate={onNavigate} />
        <DraftsCard data={data} onNavigate={onNavigate} />
        <NetworkCard data={data} onNavigate={onNavigate} />
        <FeedCard data={data} onNavigate={onNavigate} />
        <AdviceCard home={home} data={data} onNavigate={onNavigate} />
        <FreshnessCard data={data} onNavigate={onNavigate} />
        <ProfileCard data={data} onNavigate={onNavigate} />
      </div>
    </div>
  );
}
