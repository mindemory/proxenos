import { formatDateTime, timeAgo } from "@/lib/format";
import type { ItemsResponse } from "@/lib/types";

interface RightSidebarProps {
  feed: ItemsResponse | null;
}

export function RightSidebar({ feed }: RightSidebarProps) {
  const items = feed?.items ?? [];
  const latest = feed?.latest ?? null;

  const interests = new Map<string, number>();
  for (const it of items) {
    if (it.interest) interests.set(it.interest, (interests.get(it.interest) ?? 0) + 1);
  }
  const topInterests = [...interests].sort((a, b) => b[1] - a[1]).slice(0, 6);

  const reactions = [
    { label: "Useful", count: items.filter((i) => i.reaction === "useful").length },
    { label: "Not me", count: items.filter((i) => i.reaction === "not_me").length },
    { label: "Saved", count: items.filter((i) => i.reaction === "save").length },
    { label: "Opened", count: items.filter((i) => i.opened).length },
  ];

  return (
    <aside className="w-[350px] flex-shrink-0 sticky top-0 h-screen p-6 hidden xl:flex flex-col gap-6">
      <div className="bg-surface rounded-2xl p-6 shadow-soft">
        <h2 className="font-bold text-xl mb-4 text-text-primary">Latest batch</h2>
        {latest && feed ? (
          <div className="space-y-1">
            <div className="text-3xl font-bold">{timeAgo(latest.ts, feed.now)}</div>
            <div className="text-sm text-text-secondary">
              {formatDateTime(latest.ts)} · {latest.count} items
            </div>
            <div className="text-sm text-text-secondary">Checks for new batches every 5 minutes.</div>
          </div>
        ) : (
          <div className="text-sm text-text-secondary">{feed ? "No batches yet." : "Loading..."}</div>
        )}
      </div>

      <div className="bg-surface rounded-2xl p-6 shadow-soft">
        <h2 className="font-bold text-xl mb-4 text-text-primary">Interests in view</h2>
        {topInterests.length > 0 ? (
          <div className="space-y-3">
            {topInterests.map(([name, count]) => (
              <div key={name} className="flex items-center justify-between gap-3">
                <span className="font-bold truncate">{name}</span>
                <span className="bg-primary/20 text-yellow-700 text-xs font-bold px-2 py-1 rounded-full">{count}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-sm text-text-secondary">Nothing ranked yet.</div>
        )}
      </div>

      <div className="bg-surface rounded-2xl p-6 shadow-soft">
        <h2 className="font-bold text-xl mb-4 text-text-primary">Your reactions</h2>
        <div className="grid grid-cols-2 gap-3">
          {reactions.map((r) => (
            <div key={r.label} className="bg-background rounded-xl p-3">
              <div className="text-2xl font-bold">{r.count}</div>
              <div className="text-sm text-text-secondary">{r.label}</div>
            </div>
          ))}
        </div>
        <p className="text-xs text-text-secondary mt-3">On the batches shown in the feed.</p>
      </div>
    </aside>
  );
}
