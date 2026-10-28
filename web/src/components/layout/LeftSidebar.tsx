import { RefreshCw } from "lucide-react";

import { Wordmark } from "@/components/Logo";
import { cn } from "@/lib/utils";

import { NAV_ITEMS, SOON_ITEMS, type NavCounts, type NavItem, type View } from "./nav";

interface LeftSidebarProps {
  onNavigate: (view: View) => void;
  currentView: View;
  hasNew?: boolean;
  counts?: NavCounts;
  onRefresh?: () => void;
}

const ROW = "flex w-full items-center gap-3 rounded-2xl border px-3 py-2 text-left text-[15px] transition-colors";

function NavButton({
  item,
  active,
  count,
  dot,
  onClick,
}: {
  item: NavItem;
  active: boolean;
  count?: number;
  dot?: boolean;
  onClick: () => void;
}) {
  return (
    <li>
      <button
        onClick={onClick}
        aria-current={active ? "page" : undefined}
        className={cn(ROW, active ? "border-accent bg-surface text-accent" : "border-transparent text-ink hover:bg-surface")}
      >
        <item.icon size={18} strokeWidth={2} className={active ? "text-accent" : "text-muted"} />
        <span className="flex-1 min-w-0 truncate">{item.label}</span>
        {dot && <span className="w-2 h-2 rounded-full bg-accent" aria-label="New items" />}
        {count ? (
          <span className="num text-xs text-muted" aria-label={`${count} open`}>
            {count}
          </span>
        ) : null}
      </button>
    </li>
  );
}

export function LeftSidebar({ onNavigate, currentView, hasNew = false, counts = {}, onRefresh }: LeftSidebarProps) {
  const button = (item: NavItem) => (
    <NavButton
      key={item.id}
      item={item}
      active={currentView === item.id}
      count={counts[item.id]}
      dot={item.id === "feed" && hasNew}
      onClick={() => onNavigate(item.id)}
    />
  );

  return (
    <aside className="w-[232px] flex-shrink-0 sticky top-0 h-screen px-4 py-5 hidden md:flex flex-col">
      <button onClick={() => onNavigate("home")} className="px-3 pb-6 self-start rounded-xl" aria-label="Twin, home">
        <Wordmark />
      </button>

      <nav aria-label="Views" className="flex-1 min-h-0 overflow-y-auto space-y-5 -mx-1 px-1">
        <ul className="space-y-0.5">{NAV_ITEMS.filter((i) => i.id === "home").map(button)}</ul>

        <div>
          <div className="eyebrow px-3 mb-1.5">Clones</div>
          <ul className="space-y-0.5">
            {NAV_ITEMS.filter((i) => i.clone).map(button)}
            {SOON_ITEMS.map((s) => (
              <li key={s.label}>
                <button
                  disabled
                  title={`${s.label}: not built yet`}
                  className={cn(ROW, "border-transparent text-muted/70 cursor-not-allowed")}
                >
                  <s.icon size={18} strokeWidth={2} className="text-muted/50" />
                  <span className="flex-1 min-w-0 truncate">{s.label}</span>
                  <span className="text-[10px] uppercase tracking-wider">soon</span>
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <div className="eyebrow px-3 mb-1.5">You</div>
          <ul className="space-y-0.5">{NAV_ITEMS.filter((i) => !i.clone && i.id !== "home").map(button)}</ul>
        </div>
      </nav>

      <button
        onClick={onRefresh}
        className="mt-4 flex items-center justify-center gap-2 rounded-2xl border border-line-strong bg-surface px-4 py-2.5 text-sm text-ink hover:bg-surface-2 transition-colors"
      >
        <RefreshCw size={15} strokeWidth={2} />
        Refresh
      </button>
    </aside>
  );
}
