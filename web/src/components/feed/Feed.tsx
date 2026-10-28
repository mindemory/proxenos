import { Compass, Sparkles } from "lucide-react";

import { EmptyState, ErrorBanner, NoVault } from "@/components/EmptyState";
import { FeedSkeleton } from "@/components/Skeleton";
import { formatDateTime, timeAgo } from "@/lib/format";
import type { FeedItem, ItemsResponse, Reaction } from "@/lib/types";

import { ItemCard } from "./ItemCard";

export type Tab = "for_you" | "explore";

interface FeedProps {
  data: ItemsResponse | null;
  error: string | null;
  flashId?: string | null;
  tab: Tab;
  onReact: (item: FeedItem, reaction: Reaction) => void;
  onOpen: (item: FeedItem) => void;
  onDismissError?: () => void;
}

export function Feed({ data, error, flashId, tab, onReact, onOpen, onDismissError }: FeedProps) {
  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load the feed: ${error}`} /> : <FeedSkeleton />;
  }

  if (!data.vault.exists) return <NoVault path={data.vault.path} />;

  if (data.items.length === 0) {
    return (
      <EmptyState icon={Sparkles} title="No items yet" command="proxenos clone tracker">
        The tracker fetches papers, news and posts every few hours and ranks them against your profile. Run it once to
        fill this feed.
      </EmptyState>
    );
  }

  const explore = tab === "explore";
  const shown = data.items.filter((it) => it.explore === explore);

  if (shown.length === 0) {
    return (
      <EmptyState
        icon={explore ? Compass : Sparkles}
        title={explore ? "Nothing to explore in these batches" : "Nothing picked for you in these batches"}
        command="proxenos clone tracker"
      >
        {explore
          ? "About a fifth of each batch is adjacent or contrarian material. The next batch should bring some."
          : "Every item in the latest batches is an exploration pick. Check the Explore tab, or run the tracker again."}
      </EmptyState>
    );
  }

  // Group by batch, keeping the server's order (newest batch first, then score).
  const groups: { batch: string; ts: string; items: FeedItem[] }[] = [];
  for (const it of shown) {
    const last = groups[groups.length - 1];
    if (last && last.batch === it.batch) last.items.push(it);
    else groups.push({ batch: it.batch, ts: it.ts, items: [it] });
  }

  return (
    <div className="pb-24 md:pb-20">
      {error && <ErrorBanner message={error} onDismiss={onDismissError} />}
      {groups.map((g, i) => (
        <section key={g.batch}>
          <div className="px-4 sm:px-6 py-2 border-b border-line bg-surface/60 flex justify-between gap-2">
            <span className="eyebrow">{i === 0 ? "Latest batch" : "Earlier batch"}</span>
            <span className="num text-xs text-muted" title={formatDateTime(g.ts)}>
              {timeAgo(g.ts, data.now)} · {g.items.length}
            </span>
          </div>
          <div className="divide-y divide-line border-b border-line">
            {g.items.map((it) => (
              <ItemCard key={it.id} item={it} flash={flashId === it.id} onReact={onReact} onOpen={onOpen} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
