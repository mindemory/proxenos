import { Lightbulb, ListTodo, PenLine, RefreshCw, type LucideIcon } from "lucide-react";

import { Logo } from "@/components/Logo";
import type { useHome } from "@/lib/client";
import { formatDateTime, freshness, freshnessLine, greeting, longDay, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

import { CommandBox, type CommandBoxProps } from "./CommandBox";
import type { NavCounts, View } from "./nav";

type HomeState = ReturnType<typeof useHome>;

interface TopBarProps extends CommandBoxProps {
  home: HomeState;
  counts: NavCounts;
  refreshing: boolean;
}

/** How fresh the newest sync is, as a dot colour and a line of text. */
function syncState(home: HomeState): { dot: string; text: string; title: string } {
  const data = home.data;
  if (!data) {
    return home.error
      ? { dot: "bg-bad-ink", text: "Can't load", title: home.error }
      : { dot: "bg-muted/60", text: "Loading", title: "" };
  }
  const times = data.sources.map((s) => s.lastSync).filter((t): t is string => t !== null);
  if (times.length === 0) return { dot: "bg-muted/60", text: "Not synced", title: "No source has synced yet." };
  const newest = times.reduce((a, b) => (Date.parse(a) >= Date.parse(b) ? a : b));
  const stale = data.sources.filter((s) => s.lastSync && freshness(s.lastSync, data.now).label === "Stale").length;
  const line = freshnessLine(data.sources, data.now);
  return {
    dot: freshness(newest, data.now).dot,
    text: `Synced ${timeAgo(newest, data.now)}`,
    title: `${formatDateTime(newest)}${stale ? ` · ${stale} ${stale === 1 ? "source is" : "sources are"} over 3 days behind` : ""}\n${line}`,
  };
}

function Count({
  icon: Icon,
  label,
  value,
  view,
  onNavigate,
}: {
  icon: LucideIcon;
  label: string;
  value: number | undefined;
  view: View;
  onNavigate: (v: View) => void;
}) {
  return (
    <button
      onClick={() => onNavigate(view)}
      title={`${label}: ${value ?? "none yet"}`}
      aria-label={`${label}: ${value ?? "none yet"}`}
      className="inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-xs text-muted hover:border-line-strong hover:text-ink transition-colors"
    >
      <Icon size={13} />
      <span className="num text-ink">{value ?? "–"}</span>
    </button>
  );
}

/** The top bar: the greeting, the command box, the open counts, and when things last synced. */
export function TopBar({ home, counts, refreshing, onNavigate, onFind, onNetworkTab, onRefresh }: TopBarProps) {
  const sync = syncState(home);
  const data = home.data;
  return (
    <header className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b border-line bg-bg/85 px-3 backdrop-blur-md sm:px-5">
      <button onClick={() => onNavigate("home")} className="md:hidden flex-shrink-0 rounded-full p-1" aria-label="Twin, home">
        <Logo size={26} className="text-accent" />
      </button>

      <div className="hidden sm:block min-w-0 flex-shrink-0 max-w-[16rem] lg:max-w-[22rem] leading-tight">
        <p className="font-display text-xl text-ink truncate">
          {data ? `${greeting(data.now)}${data.name ? `, ${data.name}` : ""}` : "Twin"}
        </p>
        {data && <p className="text-xs text-muted truncate">{longDay(data.now)}</p>}
      </div>

      <CommandBox onNavigate={onNavigate} onFind={onFind} onNetworkTab={onNetworkTab} onRefresh={onRefresh} />

      <div className="ml-auto flex items-center gap-2 flex-shrink-0">
        <div className="hidden lg:flex items-center gap-1.5">
          <Count icon={ListTodo} label="Open tasks" value={counts.tasks} view="tasks" onNavigate={onNavigate} />
          <Count icon={PenLine} label="Drafts awaiting you" value={counts.drafts} view="drafts" onNavigate={onNavigate} />
          <Count icon={Lightbulb} label="Unanswered advice" value={counts.advice} view="advice" onNavigate={onNavigate} />
        </div>

        <button
          onClick={() => onNavigate("status")}
          title={sync.title || undefined}
          aria-label={`${sync.text}. Open sync status`}
          className="inline-flex items-center gap-2 rounded-full px-2 py-1.5 text-xs text-muted hover:text-ink"
        >
          <span className={cn("h-2 w-2 rounded-full", sync.dot)} aria-hidden="true" />
          <span className="num hidden md:inline whitespace-nowrap">{sync.text}</span>
        </button>

        <button
          onClick={onRefresh}
          aria-label="Refresh"
          title="Refresh"
          className="flex h-9 w-9 items-center justify-center rounded-full border border-line-strong text-muted transition-colors hover:bg-surface hover:text-ink"
        >
          <RefreshCw size={15} className={cn(refreshing && "animate-spin")} />
        </button>
      </div>
    </header>
  );
}
