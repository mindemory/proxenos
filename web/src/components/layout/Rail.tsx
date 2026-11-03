"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";

import { Logo, Wordmark } from "@/components/Logo";
import { forgetEntered } from "@/lib/entry";
import { useScrollEdges } from "@/lib/hooks";
import { setRailCollapsed, useRailCollapsed } from "@/lib/rail";
import { cn } from "@/lib/utils";

import { NAV_GROUPS, NAV_ITEMS, type NavCounts, type View } from "./nav";

interface RailProps {
  onNavigate: (view: View) => void;
  currentView: View;
  hasNew?: boolean;
  counts?: NavCounts;
}

/** A label shown beside the sidebar for what the pointer or focus is on. */
interface Tip {
  el: HTMLElement;
  text: string;
  note?: string;
  top: number;
  left: number;
  /** Shown with labels beside the icons too, for a control that has no label of its own. */
  always: boolean;
}

/** How far a focused item is kept from the list's ends, clear of their fade (1.75rem). */
const fadeClearance = () => 1.75 * parseFloat(getComputedStyle(document.documentElement).fontSize);

/** Where a tip for `el` goes: level with it, just past the sidebar's edge. */
function place(el: HTMLElement) {
  const r = el.getBoundingClientRect();
  const edge = el.closest("aside")?.getBoundingClientRect().right ?? r.right;
  return { top: r.top + r.height / 2, left: edge + 8 };
}

/** Scroll the list just enough that `el` sits clear of its faded ends. */
function reveal(list: HTMLElement, el: HTMLElement) {
  const clear = fadeClearance();
  const box = list.getBoundingClientRect();
  const r = el.getBoundingClientRect();
  if (r.top < box.top + clear) list.scrollBy({ top: r.top - (box.top + clear) });
  else if (r.bottom > box.bottom - clear) list.scrollBy({ top: r.bottom - (box.bottom - clear) });
}

/**
 * The sidebar down the left edge: every view by group, with its name beside its icon, or icons
 * only, which the button at the top switches and this device remembers (lib/rail.ts). The list
 * scrolls on its own when the window is short or the text large, and fades at an end with more
 * past it; its scrollbar is thin, and hidden in the narrow rail, where it would crowd the icons.
 * Icons only, each names itself beside the sidebar on hover or focus. The mark at the top goes
 * back to the landing page.
 */
export function Rail({ onNavigate, currentView, hasNew = false, counts = {} }: RailProps) {
  const collapsed = useRailCollapsed();
  const [list, setList] = useState<HTMLElement | null>(null);
  const edges = useScrollEdges(list);
  const [tip, setTip] = useState<Tip | null>(null);

  const show = (el: HTMLElement, text: string, note: string | undefined, always: boolean) =>
    setTip({ el, text, note, always, ...place(el) });
  const hide = (el: HTMLElement) => setTip((t) => (t?.el === el ? null : t));
  const tipFor = (text: string, note?: string, always = false) => ({
    onMouseEnter: (e: React.MouseEvent<HTMLElement>) => show(e.currentTarget, text, note, always),
    onFocus: (e: React.FocusEvent<HTMLElement>) => {
      if (list?.contains(e.currentTarget)) reveal(list, e.currentTarget);
      show(e.currentTarget, text, note, always);
    },
    onMouseLeave: (e: React.MouseEvent<HTMLElement>) => hide(e.currentTarget),
    onBlur: (e: React.FocusEvent<HTMLElement>) => hide(e.currentTarget),
  });

  // A tip follows its item as the list scrolls, and goes once the item is out of sight.
  const follow = () =>
    setTip((t) => {
      if (!t || !list?.contains(t.el)) return t;
      const box = list.getBoundingClientRect();
      const r = t.el.getBoundingClientRect();
      return r.bottom < box.top || r.top > box.bottom ? null : { ...t, ...place(t.el) };
    });

  // Escape puts a tip away, as content shown on hover or focus should go when asked.
  useEffect(() => {
    if (!tip) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setTip(null);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [tip]);

  // The open view stays in sight, so a view opened from elsewhere shows where it lives.
  useEffect(() => {
    const el = list?.querySelector<HTMLElement>('[aria-current="page"]');
    if (list && el) reveal(list, el);
  }, [currentView, list, collapsed]);

  const toggle = collapsed ? "Expand the sidebar" : "Collapse the sidebar";

  return (
    <aside
      className="sticky top-0 hidden h-dvh w-[13.75rem] flex-shrink-0 flex-col border-r border-line bg-surface/40 md:flex rail-icons:w-16"
    >
      <div className="flex flex-none items-center gap-1 px-3 pb-2 pt-3 rail-icons:flex-col rail-icons:gap-1.5 rail-icons:px-2">
        <Link
          href="/"
          onClick={forgetEntered}
          aria-label="Proxenos: back to the landing page"
          {...tipFor("Proxenos")}
          className="flex h-10 min-w-0 flex-1 items-center gap-2.5 rounded-xl px-2 hover:bg-surface-2 rail-icons:w-10 rail-icons:flex-none rail-icons:justify-center rail-icons:px-0"
        >
          <Logo size={26} className="flex-shrink-0 text-accent" />
          <Wordmark className="truncate text-[1.6rem] rail-icons:hidden" />
        </Link>
        <button
          type="button"
          onClick={() => setRailCollapsed(!collapsed)}
          aria-label={toggle}
          {...tipFor(toggle, undefined, true)}
          className="flex h-9 w-9 flex-none items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-ink rail-icons:h-10 rail-icons:w-10 rail-icons:rounded-xl"
        >
          <PanelLeftClose size={18} className="rail-icons:hidden" aria-hidden="true" />
          <PanelLeftOpen size={18} className="hidden rail-icons:block" aria-hidden="true" />
        </button>
      </div>

      <nav
        ref={setList}
        aria-label="Views"
        onScroll={follow}
        data-above={edges.above || undefined}
        data-below={edges.below || undefined}
        className="scroll-fade min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pb-4 pt-1 [scrollbar-width:thin] rail-icons:px-2 rail-icons:[scrollbar-width:none]"
      >
        <div>
          {NAV_GROUPS.map((group, i) => (
            <div key={group.id} className={cn("relative", i > 0 && "mt-4 rail-icons:mt-2")}>
              <h2 id={`nav-${group.id}`} className="smallcaps px-2.5 pb-1.5 text-faint rail-icons:sr-only">
                {group.label}
              </h2>
              {i > 0 && <span className="mx-auto mb-2 hidden h-px w-6 bg-line-strong rail-icons:block" aria-hidden="true" />}
              <ul aria-labelledby={`nav-${group.id}`} className="flex flex-col gap-0.5 rail-icons:gap-1">
                {NAV_ITEMS.filter((item) => item.group === group.id).map((item) => {
                  const active = currentView === item.id;
                  const count = counts[item.id];
                  const dot = item.id === "feed" && hasNew && !count;
                  return (
                    <li key={item.id}>
                      <button
                        type="button"
                        onClick={() => onNavigate(item.id)}
                        aria-current={active ? "page" : undefined}
                        {...tipFor(item.label, count ? String(count) : dot ? "new" : undefined)}
                        className={cn(
                          "relative flex min-h-9 w-full items-center gap-3 rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors",
                          "rail-icons:mx-auto rail-icons:h-10 rail-icons:min-h-0 rail-icons:w-10 rail-icons:justify-center rail-icons:rounded-xl rail-icons:p-0",
                          active ? "bg-accent/10 text-ink" : "text-muted hover:bg-surface-2 hover:text-ink",
                        )}
                      >
                        {active && (
                          <span className="absolute -left-3 top-2 bottom-2 w-[3px] rounded-r-full bg-accent" aria-hidden="true" />
                        )}
                        <item.icon size={18} strokeWidth={2} className={cn("flex-shrink-0", active && "text-accent")} aria-hidden="true" />
                        <span className="min-w-0 flex-1 leading-snug rail-icons:sr-only">{item.label}</span>
                        {count ? (
                          <span
                            className="num min-w-5 rounded-full bg-accent px-1.5 text-center text-[0.6875rem] font-medium leading-5 text-accent-ink rail-icons:absolute rail-icons:-right-1 rail-icons:-top-1 rail-icons:min-w-4 rail-icons:px-1 rail-icons:text-[0.625rem] rail-icons:leading-4"
                            aria-hidden="true"
                          >
                            {count > 99 ? "99+" : count}
                          </span>
                        ) : dot ? (
                          <span
                            className="mr-1 h-2 w-2 flex-shrink-0 rounded-full bg-accent rail-icons:absolute rail-icons:right-1.5 rail-icons:top-1.5 rail-icons:mr-0"
                            aria-hidden="true"
                          />
                        ) : null}
                        {count ? <span className="sr-only">, {count} open</span> : dot ? <span className="sr-only">, new items</span> : null}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      </nav>

      {tip && (
        <span
          aria-hidden="true"
          style={{ top: tip.top, left: tip.left }}
          className={cn(
            "fade-in pointer-events-none fixed z-50 -translate-y-1/2 whitespace-nowrap rounded-lg border border-line-strong bg-surface-2 px-2.5 py-1 text-xs text-ink shadow-pop",
            !tip.always && "hidden rail-icons:block",
          )}
        >
          {tip.text}
          {tip.note && <span className="num ml-1.5 text-muted">{tip.note}</span>}
        </span>
      )}
    </aside>
  );
}
