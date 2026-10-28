"use client";

import { ArrowRight } from "lucide-react";

import { SuggestionCard } from "@/components/advice/SuggestionCard";
import { ErrorBanner, LoadingRows, NoVault, QuietLine } from "@/components/EmptyState";
import { TitleLink } from "@/components/feed/ItemCard";
import type { View } from "@/components/layout/nav";
import { Markdown } from "@/components/Markdown";
import { TaskRow } from "@/components/tasks/TaskRow";
import { sendFeedback, type useHome } from "@/lib/client";
import { formatDateTime, freshnessLine, greeting, localDay, percent, shortDate, sourceLabel, timeAgo } from "@/lib/format";
import { byUrgency, isUrgent } from "@/lib/tasks";
import type { FeedItem, HomeResponse } from "@/lib/types";

type HomeState = ReturnType<typeof useHome>;

interface HomeProps {
  home: HomeState;
  onNavigate: (view: View) => void;
}

/** One calm section of the brief: a heading, a link to the full view, and a little content. */
function Block({
  title,
  link,
  onLink,
  children,
}: {
  title: string;
  link: string;
  onLink: () => void;
  children: React.ReactNode;
}) {
  return (
    <section className="py-6 border-t border-line">
      <div className="flex items-baseline justify-between gap-3 mb-3">
        <h3 className="font-display text-2xl text-ink">{title}</h3>
        <button
          onClick={onLink}
          className="inline-flex items-center gap-1 text-sm text-accent whitespace-nowrap rounded hover:underline underline-offset-4"
        >
          {link}
          <ArrowRight size={14} />
        </button>
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function Meta({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-muted leading-relaxed">{children}</p>;
}

function Pick({ item }: { item: FeedItem }) {
  const open = (it: FeedItem) =>
    sendFeedback(it.id, "open").catch(() => {
      // Opening still works; only the log line is lost.
    });
  return (
    <li className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="flex items-center gap-2 text-xs text-muted min-w-0">
        <span className="truncate">{sourceLabel(item.source)}</span>
        <span className="eyebrow">{item.kind}</span>
        <span className="num ml-auto text-accent" title="Match with your profile">
          {percent(item.score)}%
        </span>
      </div>
      <h4 className="font-display text-lg leading-snug text-ink mt-1 break-words">
        <TitleLink item={item} onOpen={open} />
      </h4>
      {item.why && <p className="text-sm text-muted leading-relaxed mt-1 line-clamp-2 break-words">{item.why}</p>}
    </li>
  );
}

function FeedBlock({ data, onNavigate }: { data: HomeResponse; onNavigate: (v: View) => void }) {
  const { newCount, top, latest } = data.feed;
  return (
    <Block title="Feed" link="Open feed" onLink={() => onNavigate("feed")}>
      {!latest ? (
        <QuietLine command="twin clone tracker">No feed yet. The tracker fills it:</QuietLine>
      ) : (
        <>
          <Meta>
            {data.since ? (
              newCount > 0 ? (
                <>
                  <span className="num text-ink">{newCount}</span> new {newCount === 1 ? "item" : "items"} since then.
                  Top picks:
                </>
              ) : (
                <>
                  Nothing new since then. The latest batch came in{" "}
                  <span className="num">{timeAgo(latest.ts, data.now)}</span>.
                </>
              )
            ) : (
              <>
                <span className="num text-ink">{newCount}</span> {newCount === 1 ? "item" : "items"} in the latest
                batch, <span className="num">{timeAgo(latest.ts, data.now)}</span>. Top picks:
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
    </Block>
  );
}

function TasksBlock({ home, data, onNavigate }: { home: HomeState; data: HomeResponse; onNavigate: (v: View) => void }) {
  const open = data.tasks.actionable.filter((t) => t.action === null);
  const urgent = open.filter((t) => isUrgent(t, localDay(data.now))).length;
  const top = byUrgency(open, data.now).slice(0, 3);
  return (
    <Block title="Tasks" link="All tasks" onLink={() => onNavigate("tasks")}>
      {!data.tasks.exists ? (
        <QuietLine command="twin clone tasks">No task list yet. This builds it from your messages:</QuietLine>
      ) : (
        <>
          <Meta>
            <span className="num text-ink">{open.length}</span> open
            {urgent > 0 && (
              <>
                , <span className="num text-warn-ink">{urgent}</span> overdue or due soon
              </>
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
            <ul className="rounded-xl border border-line bg-surface divide-y divide-line overflow-hidden">
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
    </Block>
  );
}

function AdviceBlock({ home, data, onNavigate }: { home: HomeState; data: HomeResponse; onNavigate: (v: View) => void }) {
  const a = data.advice;
  return (
    <Block title="Advice" link="All advice" onLink={() => onNavigate("advice")}>
      {!a.exists ? (
        <QuietLine command="twin clone advisor">No advice yet. Once the profile exists, this writes some:</QuietLine>
      ) : !a.pick ? (
        <Meta>The newest advice file has no suggestions.</Meta>
      ) : (
        <>
          <Meta>
            <span className="num text-ink">{a.unanswered}</span> of <span className="num">{a.total}</span> not answered,
            from <span className="num">{shortDate(a.date, data.now)}</span>.
          </Meta>
          <SuggestionCard s={a.pick} now={data.now} actions={["useful", "not_me"]} onReact={home.reactAdvice} compact />
        </>
      )}
    </Block>
  );
}

/** One quiet line about the network, linking to the full view. */
function NetworkLine({ data, onNavigate }: { data: HomeResponse; onNavigate: (v: View) => void }) {
  const n = data.network;
  return (
    <section className="py-6 border-t border-line flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
      <div className="flex-1 min-w-0 text-sm text-muted leading-relaxed">
        {!n.exists ? (
          <QuietLine command="twin clone network --people-only">No people index yet:</QuietLine>
        ) : (
          <p className="break-words">
            <span className="num text-ink">{n.people.toLocaleString()}</span> people in your network,{" "}
            <span className="num">{n.met.toLocaleString()}</span> met.
            {n.outreach && (
              <>
                {" "}
                Reach out to <span className="text-ink">{n.outreach.name}</span>
                {n.outreach.ask && <>: {n.outreach.ask}</>}
              </>
            )}
          </p>
        )}
      </div>
      <button
        onClick={() => onNavigate("network")}
        className="inline-flex items-center gap-1 text-sm text-accent whitespace-nowrap rounded hover:underline underline-offset-4"
      >
        Network
        <ArrowRight size={14} />
      </button>
    </section>
  );
}

function SelfBlock({ data, onNavigate }: { data: HomeResponse; onNavigate: (v: View) => void }) {
  const s = data.self;
  const latest = s.latest;
  return (
    <Block title="Your profile" link="Open profile" onLink={() => onNavigate("twin")}>
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
            <div className="border-l-2 border-accent/40 pl-4">
              <Markdown source={latest.body} compact />
            </div>
          )}
        </>
      )}
    </Block>
  );
}

function SourcesLine({ data, onNavigate }: { data: HomeResponse; onNavigate: (v: View) => void }) {
  const line = freshnessLine(data.sources, data.now);
  const any = data.sources.some((s) => s.lastSync);
  return (
    <section className="py-6 border-t border-line flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
      {any ? (
        <p className="text-sm text-muted leading-relaxed min-w-0 flex-1">{line}</p>
      ) : (
        <div className="flex-1 min-w-0">
          <QuietLine command="twin sync">Nothing synced yet. This pulls every source:</QuietLine>
        </div>
      )}
      <button
        onClick={() => onNavigate("status")}
        className="inline-flex items-center gap-1 text-sm text-accent whitespace-nowrap rounded hover:underline underline-offset-4"
      >
        Sync status
        <ArrowRight size={14} />
      </button>
    </section>
  );
}

export function Home({ home, onNavigate }: HomeProps) {
  const { data, error, clearError } = home;

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load the brief: ${error}`} /> : <LoadingRows />;
  }

  if (!data.vault.exists) return <NoVault path={data.vault.path} />;

  return (
    <div className="pb-24 md:pb-20">
      {error && <ErrorBanner message={error} onDismiss={clearError} />}
      <div className="px-4 sm:px-8 pt-8 max-w-2xl">
        <h2 className="font-display text-[2.4rem] sm:text-5xl leading-[1.1] tracking-tight text-ink">
          {greeting(data.now)}
          {data.name ? `, ${data.name}` : ""}.
        </h2>
        <p className="text-muted mt-3 mb-4" title={data.since ? formatDateTime(data.since) : undefined}>
          {data.since ? (
            <>
              Since you were last here, <span className="num">{timeAgo(data.since, data.now)}</span>:
            </>
          ) : (
            "Here is where things stand."
          )}
        </p>

        <FeedBlock data={data} onNavigate={onNavigate} />
        <TasksBlock home={home} data={data} onNavigate={onNavigate} />
        <AdviceBlock home={home} data={data} onNavigate={onNavigate} />
        <NetworkLine data={data} onNavigate={onNavigate} />
        <SelfBlock data={data} onNavigate={onNavigate} />
        <SourcesLine data={data} onNavigate={onNavigate} />
      </div>
    </div>
  );
}

