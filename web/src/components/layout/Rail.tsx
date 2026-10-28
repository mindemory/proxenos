import { Logo } from "@/components/Logo";
import { cn } from "@/lib/utils";

import { NAV_ITEMS, type NavCounts, type NavItem, type View } from "./nav";

interface RailProps {
  onNavigate: (view: View) => void;
  currentView: View;
  hasNew?: boolean;
  counts?: NavCounts;
}

/** A label that shows beside a rail icon on hover or focus. */
export function Tip({ children }: { children: React.ReactNode }) {
  return (
    <span
      role="presentation"
      className="pointer-events-none absolute left-full top-1/2 z-50 ml-3 -translate-y-1/2 whitespace-nowrap rounded-lg border border-line-strong bg-surface-2 px-2.5 py-1 text-xs text-ink shadow-pop opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-visible:opacity-100"
    >
      {children}
    </span>
  );
}

function RailButton({
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
  const name = count ? `${item.label}, ${count} open` : item.label;
  return (
    <li>
      <button
        onClick={onClick}
        aria-current={active ? "page" : undefined}
        aria-label={name}
        className={cn(
          "group relative flex h-10 w-10 items-center justify-center rounded-xl transition-colors",
          active ? "bg-accent/10 text-accent" : "text-muted hover:bg-surface-2 hover:text-ink",
        )}
      >
        {active && <span className="absolute -left-2.5 top-2.5 bottom-2.5 w-[3px] rounded-r-full bg-accent" aria-hidden="true" />}
        <item.icon size={19} strokeWidth={2} />
        {count ? (
          <span
            className="num absolute -top-1 -right-1 min-w-[16px] rounded-full bg-accent px-1 text-center text-[10px] font-medium leading-4 text-accent-ink"
            aria-hidden="true"
          >
            {count > 99 ? "99+" : count}
          </span>
        ) : dot ? (
          <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-accent" aria-hidden="true" />
        ) : null}
        <Tip>
          {item.label}
          {count ? <span className="num ml-1.5 text-muted">{count}</span> : null}
          {dot && !count ? <span className="ml-1.5 text-muted">new</span> : null}
        </Tip>
      </button>
    </li>
  );
}

/** The slim icon rail down the left edge. Labels show in tooltips. */
export function Rail({ onNavigate, currentView, hasNew = false, counts = {} }: RailProps) {
  const section = (group: NavItem["group"]) =>
    NAV_ITEMS.filter((i) => i.group === group).map((item) => (
      <RailButton
        key={item.id}
        item={item}
        active={currentView === item.id}
        count={counts[item.id]}
        dot={item.id === "feed" && hasNew}
        onClick={() => onNavigate(item.id)}
      />
    ));

  return (
    <aside className="hidden md:flex w-[60px] flex-shrink-0 sticky top-0 h-dvh flex-col items-center border-r border-line bg-surface/40 py-3">
      <button onClick={() => onNavigate("home")} className="group relative mb-3 flex h-10 w-10 items-center justify-center rounded-xl hover:bg-surface-2" aria-label="Twin, home">
        <Logo size={26} className="text-accent" />
        <Tip>Twin</Tip>
      </button>
      <nav aria-label="Views" className="flex flex-1 min-h-0 flex-col items-center">
        <ul className="flex flex-col items-center gap-1">{section("home")}</ul>
        <span className="my-2.5 h-px w-6 bg-line-strong" aria-hidden="true" />
        <ul className="flex flex-col items-center gap-1">{section("clones")}</ul>
        <ul className="mt-auto flex flex-col items-center gap-1 pt-3">{section("you")}</ul>
      </nav>
    </aside>
  );
}

