import { Compass, FolderX, Sparkles } from "lucide-react";

import { EmptyState, ErrorBanner, LoadingRows } from "@/components/EmptyState";
import { formatDateTime, timeAgo } from "@/lib/format";
import type { FeedItem, ItemsResponse, Reaction } from "@/lib/types";

import { ItemCard } from "./ItemCard";

export type Tab = "for_you" | "explore";

interface FeedProps {
  data: ItemsResponse | null;
  error: string | null;
  tab: Tab;
  onReact: (item: FeedItem, reaction: Reaction) => void;
  onOpen: (item: FeedItem) => void;
}

export function Feed({ data, error, tab, onReact, onOpen }: FeedProps) {
  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load the feed: ${error}`} /> : <LoadingRows />;
  }

  if (!data.vault.exists) {
    return (
      <EmptyState icon={FolderX} title="No vault found" command="TWIN_VAULT=~/twin_vault">
        Looked in <code className="font-mono">{data.vault.path}</code>. Set TWIN_VAULT in the repo&apos;s
        .env or the environment, then reload.
      </EmptyState>
    );
  }

  if (data.items.length === 0) {
    return (
      <EmptyState icon={Sparkles} title="No items yet" command="twin clone tracker">
        The tracker fetches papers, news and posts every few hours and ranks them against your profile. Run it
        once to fill this feed.
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
        command="twin clone tracker"
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
      {error && <ErrorBanner message={error} />}
      {groups.map((g, i) => (
        <section key={g.batch}>
          <div className="px-4 sm:px-6 py-2 border-b border-gray-100 bg-white/40 text-xs font-bold uppercase tracking-wider text-text-secondary flex justify-between gap-2">
            <span>{i === 0 ? "Latest batch" : "Earlier batch"}</span>
            <span title={formatDateTime(g.ts)}>
              {timeAgo(g.ts, data.now)} · {g.items.length}
            </span>
          </div>
          <div className="divide-y divide-gray-100 border-b border-gray-100">
            {g.items.map((it) => (
              <ItemCard key={it.id} item={it} onReact={onReact} onOpen={onOpen} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
