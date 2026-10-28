"use client";

import { useState } from "react";
import { Check, Network as NetworkIcon, Search, ThumbsDown, ThumbsUp, type LucideIcon } from "lucide-react";

import { ActionButton, type ActionTone } from "@/components/ActionButton";
import { EmptyState, ErrorBanner, LoadingRows, NoVault, QuietLine } from "@/components/EmptyState";
import { SourceBadge } from "@/components/SourceBadge";
import { useNetwork } from "@/lib/client";
import { formatDateTime, shortDate, timeAgo } from "@/lib/format";
import type { NetworkAction, NetworkResponse, Person, Relation } from "@/lib/types";
import { cn } from "@/lib/utils";

export type NetworkTab = "people" | "projects" | "outreach";

export const NETWORK_TABS: { id: NetworkTab; label: string }[] = [
  { id: "people", label: "People" },
  { id: "projects", label: "Projects" },
  { id: "outreach", label: "Reach out" },
];

const RELATION_LABEL: Record<Relation, string> = { met: "Met", know_of: "Know of", to_read: "To read" };

const ACTIONS: { action: NetworkAction; label: string; icon: LucideIcon; tone: ActionTone; done: string }[] = [
  { action: "useful", label: "Useful", icon: ThumbsUp, tone: "ok", done: "You marked this useful" },
  { action: "not_me", label: "Not me", icon: ThumbsDown, tone: "bad", done: "You said this isn't for you" },
  { action: "done", label: "Done", icon: Check, tone: "ok", done: "You marked this done" },
];

type Idea = { id: string; action: NetworkAction | null; acted_at: string | null };
type OnReact = (item: Idea, action: NetworkAction) => void;

const PAGE = 100;

function Label({ children }: { children: React.ReactNode }) {
  return <div className="eyebrow mb-1">{children}</div>;
}

/** The accent-tinted box for the one line to act on. */
function Citation({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-accent/25 bg-accent/[0.06] p-4">
      <div className="text-[11px] leading-4 font-medium uppercase tracking-[0.08em] text-accent mb-1.5">{label}</div>
      <p className="font-display text-lg leading-snug text-ink break-words">{children}</p>
    </div>
  );
}

function Actions({ item, now, onReact }: { item: Idea; now: string; onReact: OnReact }) {
  const state = ACTIONS.find((a) => a.action === item.action);
  return (
    <div className="flex flex-wrap items-center gap-2">
      {ACTIONS.map((a) => (
        <ActionButton
          key={a.action}
          icon={a.icon}
          label={a.label}
          tone={a.tone}
          active={item.action === a.action}
          onClick={() => onReact(item, a.action)}
        />
      ))}
      {state && (
        <span className="text-xs text-muted sm:ml-auto">
          {state.done}
          {item.acted_at && (
            <>
              , <span className="num">{timeAgo(item.acted_at, now)}</span>
            </>
          )}
        </span>
      )}
    </div>
  );
}

function Generated({ at, now, children }: { at: string | null; now: string; children?: React.ReactNode }) {
  return (
    <div className="px-4 sm:px-6 py-3 border-b border-line flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-sm text-muted">
      <span>{children}</span>
      {at && (
        <span title={formatDateTime(at)}>
          Generated <span className="num">{timeAgo(at, now)}</span>
        </span>
      )}
    </div>
  );
}

// ── People ──────────────────────────────────────────────────────────────────

type Sort = "recent" | "interactions";

const seenMs = (p: Person) => {
  const t = p.last_seen ? Date.parse(p.last_seen) : NaN;
  return Number.isNaN(t) ? 0 : t;
};

function PersonRow({ p, now }: { p: Person; now: string }) {
  return (
    <li className="px-4 sm:px-6 py-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex flex-wrap items-baseline gap-x-2">
          <span className="font-medium text-ink break-words">{p.name}</span>
          {p.org && <span className="text-sm text-muted break-words">{p.org}</span>}
        </div>
        {p.interactions > 0 && (
          <span className="text-right flex-shrink-0 leading-tight" title={`${p.interactions} interactions`}>
            <span className="num text-sm text-ink block">{p.interactions.toLocaleString()}</span>
            <span className="text-[11px] text-muted">interactions</span>
          </span>
        )}
      </div>
      {p.context && <p className="text-sm text-muted leading-relaxed line-clamp-2 mt-1 break-words">{p.context}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted">
        <span className="eyebrow mr-1">{RELATION_LABEL[p.relation]}</span>
        {p.sources.map((s) => (
          <SourceBadge key={s} kind={s} />
        ))}
        {p.topics.map((t) => (
          <span key={t} className="rounded-md border border-line px-1.5 py-0.5 text-muted break-all">
            #{t}
          </span>
        ))}
        {p.last_seen && shortDate(p.last_seen, now) && (
          <span className="ml-1" title={formatDateTime(p.last_seen)}>
            last seen <span className="num text-ink/85">{shortDate(p.last_seen, now)}</span>
          </span>
        )}
      </div>
    </li>
  );
}

function People({ data }: { data: NetworkResponse }) {
  const [relations, setRelations] = useState<Relation[]>([]);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>("recent");
  const [limit, setLimit] = useState(PAGE);
  const list = data.people.list;

  if (!data.people.exists) {
    return (
      <EmptyState icon={NetworkIcon} title="No people index yet" command="twin clone network --people-only">
        The network clone indexes the people in your messages, mentions and reading: who you&apos;ve met, who you know
        of, and whose work you read.
      </EmptyState>
    );
  }

  const q = query.trim().toLowerCase();
  const shown = list
    .filter((p) => relations.length === 0 || relations.includes(p.relation))
    .filter(
      (p) =>
        !q ||
        [p.name, p.org ?? "", p.context, ...p.topics].some((f) => f.toLowerCase().includes(q)),
    )
    .sort((a, b) =>
      sort === "recent"
        ? seenMs(b) - seenMs(a) || b.interactions - a.interactions
        : b.interactions - a.interactions || seenMs(b) - seenMs(a),
    );

  const toggle = (r: Relation) => {
    setRelations((cur) => (cur.includes(r) ? cur.filter((x) => x !== r) : [...cur, r]));
    setLimit(PAGE);
  };

  return (
    <>
      <Generated at={data.people.generated} now={data.now}>
        <span className="num text-ink">{list.length.toLocaleString()}</span> people
        {shown.length !== list.length && (
          <>
            {" "}
            · showing <span className="num">{shown.length.toLocaleString()}</span>
          </>
        )}
      </Generated>

      <div className="px-4 sm:px-6 py-3 border-b border-line flex flex-wrap items-center gap-2">
        {(Object.keys(RELATION_LABEL) as Relation[]).map((r) => {
          const on = relations.includes(r);
          return (
            <button
              key={r}
              onClick={() => toggle(r)}
              aria-pressed={on}
              className={cn(
                "rounded-full border px-3 py-1 text-[13px] transition-colors whitespace-nowrap",
                on ? "border-accent/40 bg-accent/10 text-accent" : "border-line-strong text-muted hover:text-ink",
              )}
            >
              {RELATION_LABEL[r]} <span className="num">{list.filter((p) => p.relation === r).length}</span>
            </button>
          );
        })}
        <div className="flex w-full sm:w-auto sm:flex-1 items-center gap-2 sm:ml-2">
          <label className="relative flex-1 min-w-0">
            <span className="sr-only">Search people</span>
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted pointer-events-none" />
            <input
              type="search"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setLimit(PAGE);
              }}
              placeholder="Name, org or topic"
              className="w-full rounded-full border border-line-strong bg-surface pl-8 pr-3 py-1.5 text-sm text-ink placeholder:text-muted/80"
            />
          </label>
          <label className="flex-shrink-0">
            <span className="sr-only">Sort</span>
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as Sort)}
              className="rounded-full border border-line-strong bg-surface px-3 py-1.5 text-sm text-ink"
            >
              <option value="recent">Recent</option>
              <option value="interactions">Most contact</option>
            </select>
          </label>
        </div>
      </div>

      {shown.length > 0 ? (
        <ul className="divide-y divide-line border-b border-line">
          {shown.slice(0, limit).map((p) => (
            <PersonRow key={p.id} p={p} now={data.now} />
          ))}
        </ul>
      ) : (
        <p className="px-4 sm:px-6 py-6 text-sm text-muted">No one matches. Clear the search or the filters.</p>
      )}
      {shown.length > limit && (
        <div className="px-4 sm:px-6 py-4">
          <button
            onClick={() => setLimit((l) => l + PAGE)}
            className="rounded-full border border-line-strong px-4 py-1.5 text-sm text-ink hover:bg-surface-2"
          >
            Show <span className="num">{Math.min(PAGE, shown.length - limit)}</span> more
          </button>
        </div>
      )}
    </>
  );
}

// ── Projects and outreach ───────────────────────────────────────────────────

function NoIdeas() {
  return (
    <EmptyState icon={NetworkIcon} title="No projects or outreach yet" command="twin clone network">
      A full run of the network clone suggests projects that fit you and people worth contacting.{" "}
      <code className="num">twin clone network --people-only</code> builds just the people index.
    </EmptyState>
  );
}

function Projects({ data, flashId, onReact }: { data: NetworkResponse; flashId: string | null; onReact: OnReact }) {
  const people = new Map(data.people.list.map((p) => [p.id, p]));
  const { projects, to_read } = data.ideas;
  return (
    <>
      <Generated at={data.ideas.generated} now={data.now}>
        <span className="num text-ink">{projects.length}</span> {projects.length === 1 ? "project" : "projects"} ·{" "}
        <span className="num">{to_read.length}</span> to read
      </Generated>
      <div className="p-4 sm:p-6 space-y-4">
        {projects.length === 0 && (
          <QuietLine command="twin clone network">No project ideas in the last run. A new run may find some:</QuietLine>
        )}
        {projects.map((p) => (
          <article
            key={p.id}
            className={cn(
              "bg-surface border border-line rounded-2xl p-4 sm:p-5 space-y-4 transition-opacity",
              flashId === p.id && "row-flash",
              p.action === "not_me" && "opacity-60 hover:opacity-90",
            )}
          >
            <div>
              <h3 className="font-display text-2xl leading-snug text-ink break-words">{p.title}</h3>
              {p.pitch && <p className="text-[15px] text-ink/90 leading-relaxed mt-1.5 break-words">{p.pitch}</p>}
            </div>
            {p.why_you && (
              <div>
                <Label>Why you</Label>
                <p className="text-sm text-muted leading-relaxed break-words">{p.why_you}</p>
              </div>
            )}
            {p.people.length > 0 && (
              <div>
                <Label>People</Label>
                <div className="flex flex-wrap gap-1.5">
                  {p.people.map((id) => {
                    const who = people.get(id);
                    return (
                      <span
                        key={id}
                        title={who ? [who.org, who.context].filter(Boolean).join(" · ") : "Not in the people index"}
                        className={cn(
                          "rounded-full border px-2.5 py-0.5 text-xs",
                          who ? "border-line-strong text-ink" : "border-line text-muted num",
                        )}
                      >
                        {who?.name ?? id}
                      </span>
                    );
                  })}
                </div>
              </div>
            )}
            {p.first_step && <Citation label="First step">{p.first_step}</Citation>}
            <Actions item={p} now={data.now} onReact={onReact} />
          </article>
        ))}

        {to_read.length > 0 && (
          <section className="pt-4">
            <h3 className="font-display text-xl text-ink mb-2">To read</h3>
            <ul className="rounded-xl border border-line bg-surface divide-y divide-line">
              {to_read.map((r) => (
                <li
                  key={r.id}
                  className={cn(
                    "px-4 py-3 space-y-2 transition-opacity",
                    flashId === r.id && "row-flash",
                    r.action === "not_me" && "opacity-60 hover:opacity-90",
                  )}
                >
                  <div>
                    <span className="font-medium text-ink">{r.name}</span>
                    {r.why && <p className="text-sm text-muted leading-relaxed break-words">{r.why}</p>}
                  </div>
                  <Actions item={r} now={data.now} onReact={onReact} />
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </>
  );
}

function Outreach({ data, flashId, onReact }: { data: NetworkResponse; flashId: string | null; onReact: OnReact }) {
  const people = new Map(data.people.list.map((p) => [p.id, p]));
  const { outreach } = data.ideas;
  return (
    <>
      <Generated at={data.ideas.generated} now={data.now}>
        <span className="num text-ink">{outreach.filter((o) => o.action === null).length}</span> of{" "}
        <span className="num">{outreach.length}</span> not answered
      </Generated>
      <div className="p-4 sm:p-6 space-y-4">
        {outreach.length === 0 && (
          <QuietLine command="twin clone network">No one to reach out to in the last run. A new run may suggest someone:</QuietLine>
        )}
        {outreach.map((o) => {
          const who = o.person_id ? people.get(o.person_id) : undefined;
          return (
            <article
              key={o.id}
              className={cn(
                "bg-surface border border-line rounded-2xl p-4 sm:p-5 space-y-4 transition-opacity",
                flashId === o.id && "row-flash",
                o.action === "not_me" && "opacity-60 hover:opacity-90",
              )}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="font-display text-2xl leading-snug text-ink break-words">{o.name}</h3>
                  {who && (who.org || who.context) && (
                    <p className="text-sm text-muted line-clamp-1 break-words">{who.org ?? who.context}</p>
                  )}
                </div>
                {o.channel && (
                  <span className="flex-shrink-0 pt-1.5" title="Suggested channel">
                    <SourceBadge kind={o.channel} />
                  </span>
                )}
              </div>
              {o.why && (
                <div>
                  <Label>Why</Label>
                  <p className="text-sm text-ink/90 leading-relaxed break-words">{o.why}</p>
                </div>
              )}
              {o.ask && <Citation label="The ask">{o.ask}</Citation>}
              <Actions item={o} now={data.now} onReact={onReact} />
            </article>
          );
        })}
      </div>
    </>
  );
}

export function Network({ tab, onChange }: { tab: NetworkTab; onChange?: () => void }) {
  const { data, error, flashId, react, clearError } = useNetwork(onChange);

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load the network: ${error}`} /> : <LoadingRows />;
  }

  if (!data.vault.exists) return <NoVault path={data.vault.path} />;

  return (
    <div className="pb-24 md:pb-20">
      {error && <ErrorBanner message={error} onDismiss={clearError} />}
      {tab === "people" ? (
        <People data={data} />
      ) : !data.ideas.exists ? (
        <NoIdeas />
      ) : tab === "projects" ? (
        <Projects data={data} flashId={flashId} onReact={react} />
      ) : (
        <Outreach data={data} flashId={flashId} onReact={react} />
      )}
    </div>
  );
}
