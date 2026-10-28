import { ChevronRight, Lightbulb, ListTodo, Rss, type LucideIcon } from "lucide-react";

import { formatDateTime, localDay, plural, shortDate, timeAgo } from "@/lib/format";
import { isUrgent } from "@/lib/tasks";
import type { HomeResponse, ItemsResponse } from "@/lib/types";

import type { View } from "./nav";

interface RightSidebarProps {
  feed: ItemsResponse | null;
  home: HomeResponse | null;
  onNavigate: (view: View) => void;
}

function CloneRow({
  icon: Icon,
  label,
  value,
  detail,
  title,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  detail: string;
  title?: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className="group w-[calc(100%+1rem)] flex items-center gap-3 rounded-xl px-2 py-2.5 -mx-2 text-left hover:bg-surface-2 transition-colors"
    >
      <Icon size={17} className="text-muted flex-shrink-0" />
      <span className="flex-1 min-w-0">
        <span className="flex items-baseline justify-between gap-2">
          <span className="text-sm">{label}</span>
          <span className="num text-lg leading-none">{value}</span>
        </span>
        <span className="block text-xs text-muted leading-snug mt-0.5">{detail}</span>
      </span>
      <ChevronRight size={15} className="text-muted/60 group-hover:text-muted flex-shrink-0" />
    </button>
  );
}

export function RightSidebar({ feed, home, onNavigate }: RightSidebarProps) {
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

  const open = home?.tasks.actionable.filter((t) => t.action === null) ?? [];
  const urgent = home ? open.filter((t) => isUrgent(t, localDay(home.now))).length : 0;

  return (
    <aside className="w-[312px] flex-shrink-0 sticky top-0 h-screen overflow-y-auto px-5 py-5 hidden xl:flex flex-col gap-4">
      <section className="bg-surface border border-line rounded-2xl p-5">
        <h2 className="font-display text-xl mb-2">Clones</h2>
        <div className="divide-y divide-line">
          <CloneRow
            icon={ListTodo}
            label="Open tasks"
            value={home?.tasks.exists ? String(open.length) : "–"}
            detail={
              !home
                ? "Loading"
                : home.tasks.exists
                  ? `${urgent} overdue or due soon · ${home.tasks.waiting} waiting`
                  : "No list yet: twin clone tasks"
            }
            onClick={() => onNavigate("tasks")}
          />
          <CloneRow
            icon={Lightbulb}
            label="Advice"
            value={home?.advice.exists ? String(home.advice.total) : "–"}
            detail={
              !home
                ? "Loading"
                : home.advice.exists
                  ? `${home.advice.unanswered} unanswered · ${shortDate(home.advice.date, home.now)}`
                  : "None yet: twin clone advisor"
            }
            onClick={() => onNavigate("advice")}
          />
          <CloneRow
            icon={Rss}
            label="Latest batch"
            value={latest && feed ? timeAgo(latest.ts, feed.now) : "–"}
            title={latest ? formatDateTime(latest.ts) : undefined}
            detail={latest ? `${plural(latest.count, "item")} · rechecked every 5 min` : feed ? "No batches yet" : "Loading"}
            onClick={() => onNavigate("feed")}
          />
        </div>
      </section>

      <section className="bg-surface border border-line rounded-2xl p-5">
        <h2 className="font-display text-xl mb-3">Interests in view</h2>
        {topInterests.length > 0 ? (
          <ul className="space-y-2">
            {topInterests.map(([name, count]) => (
              <li key={name} className="flex items-center justify-between gap-3 text-sm">
                <span className="truncate">{name}</span>
                <span className="num text-xs text-muted">{count}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">Nothing ranked yet.</p>
        )}
      </section>

      <section className="bg-surface border border-line rounded-2xl p-5">
        <h2 className="font-display text-xl mb-3">Your reactions</h2>
        <div className="grid grid-cols-2 gap-2">
          {reactions.map((r) => (
            <div key={r.label} className="bg-bg border border-line rounded-xl px-3 py-2.5">
              <div className="num text-xl">{r.count}</div>
              <div className="text-xs text-muted">{r.label}</div>
            </div>
          ))}
        </div>
        <p className="text-xs text-muted mt-3">On the batches shown in the feed.</p>
      </section>
    </aside>
  );
}
