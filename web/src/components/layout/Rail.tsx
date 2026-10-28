"use client";

import Link from "next/link";

import { Logo, Wordmark } from "@/components/Logo";
import { forgetEntered } from "@/lib/entry";
import { cn } from "@/lib/utils";

import { NAV_ITEMS, type NavCounts, type NavItem, type View } from "./nav";

interface RailProps {
  onNavigate: (view: View) => void;
  currentView: View;
  hasNew?: boolean;
  counts?: NavCounts;
}

/** A label that shows beside a rail icon on hover or focus, while the rail is icons only. */
export function Tip({ children }: { children: React.ReactNode }) {
  return (
    <span
      role="presentation"
      className="pointer-events-none absolute left-full top-1/2 z-50 ml-3 -translate-y-1/2 whitespace-nowrap rounded-lg border border-line-strong bg-surface-2 px-2.5 py-1 text-xs text-ink opacity-0 shadow-pop transition-opacity duration-150 group-hover:opacity-100 group-focus-visible:opacity-100 xl:hidden"
    >
      {children}
    </span>
  );
}

const GROUP_LABEL: Record<NavItem["group"], string | null> = {
  home: null,
  clones: "Clones",
  you: "You",
};

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
          "group relative flex h-10 w-10 items-center justify-center rounded-xl transition-colors xl:h-9 xl:w-full xl:justify-start xl:gap-3 xl:rounded-lg xl:px-2.5",
          active ? "bg-accent/10 text-accent" : "text-muted hover:bg-surface-2 hover:text-ink",
        )}
      >
        {active && (
          <span
            className="absolute -left-2.5 top-2.5 bottom-2.5 w-[3px] rounded-r-full bg-accent xl:-left-3 xl:top-2 xl:bottom-2"
            aria-hidden="true"
          />
        )}
        <item.icon size={18} strokeWidth={2} className="flex-shrink-0" />
        <span className={cn("hidden min-w-0 flex-1 truncate text-left text-sm xl:block", active ? "text-ink" : "")}>
          {item.label}
        </span>
        {count ? (
          <span
            className="num absolute -top-1 -right-1 min-w-[16px] rounded-full bg-accent px-1 text-center text-[10px] font-medium leading-4 text-accent-ink xl:static xl:min-w-[20px] xl:px-1.5 xl:text-[11px] xl:leading-5"
            aria-hidden="true"
          >
            {count > 99 ? "99+" : count}
          </span>
        ) : dot ? (
          <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-accent xl:static xl:mr-1" aria-hidden="true" />
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

/**
 * The rail down the left edge: icons with tooltips on a laptop, a full sidebar with the
 * wordmark and labels on a wide screen. The mark at the top goes back to the landing page.
 */
export function Rail({ onNavigate, currentView, hasNew = false, counts = {} }: RailProps) {
  const section = (group: NavItem["group"]) => (
    <>
      {GROUP_LABEL[group] && <span className="smallcaps mb-1.5 hidden px-2.5 text-faint xl:block">{GROUP_LABEL[group]}</span>}
      <ul className="flex flex-col items-center gap-1 xl:items-stretch">
        {NAV_ITEMS.filter((i) => i.group === group).map((item) => (
          <RailButton
            key={item.id}
            item={item}
            active={currentView === item.id}
            count={counts[item.id]}
            dot={item.id === "feed" && hasNew}
            onClick={() => onNavigate(item.id)}
          />
        ))}
      </ul>
    </>
  );

  return (
    <aside className="sticky top-0 hidden h-dvh w-[64px] flex-shrink-0 flex-col border-r border-line bg-surface/40 px-3 py-3 md:flex xl:w-60 xl:px-3.5 xl:py-4">
      <Link
        href="/"
        onClick={forgetEntered}
        className="group relative mb-4 flex h-10 w-10 items-center justify-center rounded-xl hover:bg-surface-2 xl:h-12 xl:w-full xl:justify-start xl:gap-2.5 xl:px-2"
        aria-label="Proxenos: back to the landing page"
      >
        <Logo size={26} className="flex-shrink-0 text-accent" />
        <Wordmark className="hidden text-[1.7rem] xl:inline" />
        <Tip>Proxenos</Tip>
      </Link>
      <nav aria-label="Views" className="flex min-h-0 flex-1 flex-col items-center xl:items-stretch">
        {section("home")}
        <span className="my-3 h-px w-6 bg-line-strong xl:w-full xl:bg-line" aria-hidden="true" />
        {section("clones")}
        <div className="mt-auto pt-3 xl:w-full">{section("you")}</div>
      </nav>
    </aside>
  );
}
