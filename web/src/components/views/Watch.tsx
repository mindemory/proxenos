"use client";

import { useState } from "react";
import { ArrowUpRight, Bookmark, Check, Clapperboard, ThumbsDown, type LucideIcon } from "lucide-react";

import { ActionButton, type ActionTone } from "@/components/ActionButton";
import { Command, EmptyState, ErrorBanner, NoVault } from "@/components/EmptyState";
import { ProseSkeleton } from "@/components/Skeleton";
import { useWatch } from "@/lib/client";
import { formatDateTime, shortDate, timeAgo } from "@/lib/format";
import type { WatchAction, WatchPick } from "@/lib/types";
import { cn } from "@/lib/utils";

const ACTIONS: Record<WatchAction, { label: string; icon: LucideIcon; tone: ActionTone; done: string }> = {
  want: { label: "Want to watch", icon: Bookmark, tone: "accent", done: "Saved to watch" },
  seen: { label: "Seen it", icon: Check, tone: "ok", done: "You've seen it" },
  not_me: { label: "Not for me", icon: ThumbsDown, tone: "bad", done: "You passed on it" },
};

interface PickCardProps {
  p: WatchPick;
  now: string;
  flash: boolean;
  onReact: (p: WatchPick, action: WatchAction) => void;
}

/** One pick: what it is, why it suits you, what you've seen that it follows from, where to watch it, and the three marks. */
function PickCard({ p, now, flash, onReact }: PickCardProps) {
  return (
    <article className={cn("card space-y-3 p-4 transition-opacity sm:p-5", flash && "row-flash", p.action && p.action !== "want" && "opacity-60 hover:opacity-90")}>
      <h3 className="break-words font-display text-xl leading-snug text-ink">
        {p.title}
        {p.year && <span className="num ml-2 text-base text-muted">{p.year}</span>}
      </h3>

      {p.why && <p className="break-words text-sm leading-relaxed text-ink/90">{p.why}</p>}

      {p.because.length > 0 && (
        <p className="break-words text-xs text-muted">
          <span className="eyebrow mr-1.5">Because you watched</span>
          {p.because.join(" · ")}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {p.links.map((l) => (
          <a
            key={l.url}
            href={l.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-[0.8125rem] text-muted hover:text-ink"
          >
            {l.label} <ArrowUpRight size={13} />
          </a>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {(Object.keys(ACTIONS) as WatchAction[]).map((a) => (
          <ActionButton
            key={a}
            icon={ACTIONS[a].icon}
            label={ACTIONS[a].label}
            tone={ACTIONS[a].tone}
            active={p.action === a}
            onClick={() => onReact(p, a)}
          />
        ))}
        {p.action && (
          <span className="text-xs text-muted sm:ml-auto">
            {ACTIONS[p.action].done}
            {p.acted_at && (
              <>
                , <span className="num">{timeAgo(p.acted_at, now)}</span>
              </>
            )}
          </span>
        )}
      </div>
    </article>
  );
}

interface SectionProps {
  label: string;
  note: string;
  empty: string;
  picks: WatchPick[];
  now: string;
  flashId: string | null;
  onReact: PickCardProps["onReact"];
}

function Section({ label, note, empty, picks, now, flashId, onReact }: SectionProps) {
  return (
    <section aria-label={label} className="space-y-4">
      <div>
        <p className="smallcaps text-accent">{label}</p>
        <p className="mt-1 text-sm text-muted">{note}</p>
      </div>
      {picks.length > 0 ? (
        picks.map((p) => <PickCard key={p.id} p={p} now={now} flash={flashId === p.id} onReact={onReact} />)
      ) : (
        <p className="text-sm text-muted">{empty}</p>
      )}
    </section>
  );
}

/**
 * What to watch next: films and shows you haven't seen, picked from what you loved on Letterboxd, and the films on your own watchlist
 * that suit this week. Each takes want, seen or not for me; what you want stays here, and the next week learns from all three.
 */
export function Watch({ onChange }: { onChange?: () => void }) {
  const [date, setDate] = useState<string | null>(null);
  const { data, error, flashId, react, clearError } = useWatch(date, onChange);

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load picks: ${error}`} /> : <ProseSkeleton label="Loading picks" />;
  }

  if (!data.vault.exists) return <NoVault path={data.vault.path} />;

  if (!data.date) {
    return (
      <EmptyState icon={Clapperboard} title="Nothing picked yet" command="proxenos clone watch --force">
        Once a week, your twin reads the films you&apos;ve logged on Letterboxd, what you loved and what you didn&apos;t, and picks films and
        shows you haven&apos;t seen. Set <code className="num">PROXENOS_LETTERBOXD_USER</code> so new logs come in on their own. The night job
        runs it; this runs it now.
      </EmptyState>
    );
  }

  const switching = date !== null && data.date !== date;
  const card = { now: data.now, onReact: react, flashId };

  return (
    <div className="pb-24 md:pb-20">
      {error && <ErrorBanner message={error} onDismiss={clearError} />}

      <div className="px-4 sm:px-6 py-3 border-b border-line flex flex-wrap items-center justify-between gap-x-4 gap-y-2 text-sm text-muted">
        <label className="inline-flex items-center gap-2">
          <span>Week of</span>
          <select
            value={data.date}
            onChange={(e) => setDate(e.target.value)}
            className="num bg-surface border border-line-strong rounded-full px-3 py-1 text-sm text-ink hover:border-accent/40"
          >
            {data.dates.map((d, i) => (
              <option key={d} value={d}>
                {shortDate(d, data.now)}
                {i === 0 ? " (latest)" : ""}
              </option>
            ))}
          </select>
        </label>
        {data.generated && (
          <span title={formatDateTime(data.generated)}>
            Picked <span className="num">{timeAgo(data.generated, data.now)}</span>
          </span>
        )}
      </div>

      <div className={cn("p-4 sm:p-6 space-y-8 transition-opacity", switching && "opacity-50")} aria-busy={switching}>
        {data.saved.length > 0 && (
          <Section label="Saved to watch" note="What you said you want to see, until you mark it seen." empty="" picks={data.saved} {...card} />
        )}
        <Section label="Films" note="Films you haven't seen, from what you loved." empty="No new films this week." picks={data.films} {...card} />
        <Section label="Shows" note="Series you might not have found, from your taste in films and the shows you've marked." empty="No shows this week." picks={data.shows} {...card} />
        <Section
          label="From your watchlist"
          note="Films you already wanted to see that suit this week."
          empty="Nothing from your watchlist this week."
          picks={data.watchlist}
          {...card}
        />

        <p className="text-xs text-muted">
          Each mark is appended to <code className="num">clones/watch/feedback.jsonl</code> in the vault; what you mark seen or not for me
          never comes back. Films you log on Letterboxd count as seen too. <Command>proxenos clone watch --force</Command> picks again now.
        </p>
      </div>
    </div>
  );
}
