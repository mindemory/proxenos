"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { DoorOpen, Ellipsis, RefreshCw, X } from "lucide-react";

import { Logo, Wordmark } from "@/components/Logo";
import { forgetEntered } from "@/lib/entry";
import { useScrollEdges } from "@/lib/hooks";
import { cn } from "@/lib/utils";

import { NAV_GROUPS, NAV_ITEMS, PRIMARY_MOBILE, type NavCounts, type NavItem, type View } from "./nav";

interface MobileNavProps {
  onNavigate: (view: View) => void;
  currentView: View;
  hasNew?: boolean;
  counts?: NavCounts;
  onRefresh: () => void;
}

const TAB = "relative flex min-w-0 flex-col items-center gap-0.5 rounded-xl py-1.5 text-[0.6875rem] tracking-tight transition-colors";

/**
 * Bottom tab bar below the md breakpoint: four views and "More", a sheet with every view in the
 * sidebar's groups and names, so the phone and the computer find things in the same places.
 */
export function MobileNav({ onNavigate, currentView, hasNew = false, counts = {}, onRefresh }: MobileNavProps) {
  const [open, setOpen] = useState(false);
  const more = useRef<HTMLButtonElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const [list, setList] = useState<HTMLElement | null>(null);
  const edges = useScrollEdges(list);
  const primary = NAV_ITEMS.filter((i) => PRIMARY_MOBILE.includes(i.id));
  const rest = NAV_ITEMS.filter((i) => !PRIMARY_MOBILE.includes(i.id));
  const inMore = rest.some((i) => i.id === currentView);
  const badgeInMore = rest.some((i) => (i.id === "feed" && hasNew) || counts[i.id]);

  useEffect(() => {
    if (!open) return;
    const trigger = more.current;
    close.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      trigger?.focus();
    };
  }, [open]);

  // The sheet opens with the view you're on in sight.
  useEffect(() => {
    const el = list?.querySelector<HTMLElement>('[aria-current="page"]');
    if (!list || !el) return;
    const past = el.getBoundingClientRect().bottom - list.getBoundingClientRect().bottom;
    if (past > 0) list.scrollBy({ top: past + 16 });
  }, [list]);

  const tab = (item: NavItem) => {
    const active = currentView === item.id;
    const count = counts[item.id];
    return (
      <button
        key={item.id}
        onClick={() => onNavigate(item.id)}
        aria-current={active ? "page" : undefined}
        className={cn(TAB, active ? "bg-surface text-accent" : "text-muted")}
      >
        <item.icon size={21} strokeWidth={2} aria-hidden="true" />
        <span className="max-w-full truncate">{item.label}</span>
        {count ? (
          <>
            <span
              className="num absolute top-0.5 right-[18%] min-w-[16px] rounded-full bg-accent px-1 text-center text-[0.625rem] font-medium leading-4 text-accent-ink"
              aria-hidden="true"
            >
              {count > 99 ? "99+" : count}
            </span>
            <span className="sr-only">, {count} open</span>
          </>
        ) : null}
      </button>
    );
  };

  return (
    <>
      <nav
        aria-label="Views"
        className="md:hidden fixed bottom-0 inset-x-0 z-50 h-[calc(4.25rem+env(safe-area-inset-bottom))] bg-bg/92 backdrop-blur-md border-t border-line grid grid-cols-5 gap-1 px-2 pt-1.5 pb-[env(safe-area-inset-bottom)]"
      >
        {primary.map(tab)}
        <button
          ref={more}
          onClick={() => setOpen(true)}
          aria-haspopup="dialog"
          aria-expanded={open}
          className={cn(TAB, inMore ? "bg-surface text-accent" : "text-muted")}
        >
          <Ellipsis size={21} strokeWidth={2} aria-hidden="true" />
          <span>More</span>
          {badgeInMore && <span className="absolute top-1.5 right-[28%] h-2 w-2 rounded-full bg-accent" aria-hidden="true" />}
        </button>
      </nav>

      {open && (
        <div className="md:hidden fixed inset-0 z-[65]" role="dialog" aria-modal="true" aria-label="All views">
          <button className="absolute inset-0 bg-bg/70 backdrop-blur-sm fade-in" aria-label="Close" tabIndex={-1} onClick={() => setOpen(false)} />
          <div className="sheet-in absolute inset-x-0 bottom-0 flex max-h-[88dvh] flex-col rounded-t-3xl border-t border-line-strong bg-surface pb-[max(1.25rem,env(safe-area-inset-bottom))]">
            <div className="flex-none px-4 pt-3">
              <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-line-strong" aria-hidden="true" />
              <div className="flex items-center justify-between">
                <h2 className="flex items-center gap-2">
                  <Logo size={22} className="text-accent" />
                  <Wordmark className="text-2xl" />
                </h2>
                <button ref={close} onClick={() => setOpen(false)} aria-label="Close" className="p-2 -m-2 rounded-full text-muted hover:text-ink">
                  <X size={20} />
                </button>
              </div>
            </div>

            <div
              ref={setList}
              data-above={edges.above || undefined}
              data-below={edges.below || undefined}
              className="scroll-fade min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-2"
            >
              <div>
                {NAV_GROUPS.map((group) => (
                  <div key={group.id}>
                    <h3 id={`sheet-${group.id}`} className="smallcaps px-1 pb-2 pt-4 text-faint">
                      {group.label}
                    </h3>
                    <ul aria-labelledby={`sheet-${group.id}`} className="grid grid-cols-2 gap-2">
                      {NAV_ITEMS.filter((item) => item.group === group.id).map((item) => {
                        const active = currentView === item.id;
                        const count = counts[item.id];
                        const dot = item.id === "feed" && hasNew && !count;
                        return (
                          <li key={item.id}>
                            <button
                              onClick={() => {
                                setOpen(false);
                                onNavigate(item.id);
                              }}
                              aria-current={active ? "page" : undefined}
                              className={cn(
                                "relative flex min-h-12 w-full items-center gap-2.5 rounded-xl border px-3 py-2 text-left text-sm leading-snug",
                                active ? "border-accent/40 bg-accent/10 text-ink" : "border-line text-ink hover:bg-surface-2",
                              )}
                            >
                              <item.icon size={19} strokeWidth={2} className={cn("flex-shrink-0", active ? "text-accent" : "text-muted")} aria-hidden="true" />
                              <span className="min-w-0 flex-1">{item.label}</span>
                              {count ? (
                                <span
                                  className="num min-w-[18px] flex-shrink-0 rounded-full bg-accent px-1 text-center text-[0.625rem] font-medium leading-[1.125rem] text-accent-ink"
                                  aria-hidden="true"
                                >
                                  {count > 99 ? "99+" : count}
                                </span>
                              ) : dot ? (
                                <span className="h-2 w-2 flex-shrink-0 rounded-full bg-accent" aria-hidden="true" />
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
            </div>

            <div className="grid flex-none grid-cols-2 gap-2 px-4 pt-3">
              <button
                onClick={() => {
                  setOpen(false);
                  onRefresh();
                }}
                className="flex items-center justify-center gap-2 rounded-2xl border border-line-strong py-3 text-sm text-ink hover:bg-surface-2"
              >
                <RefreshCw size={16} />
                Refresh
              </button>
              <Link
                href="/"
                onClick={forgetEntered}
                className="flex items-center justify-center gap-2 rounded-2xl border border-line-strong py-3 text-sm text-ink hover:bg-surface-2"
              >
                <DoorOpen size={16} />
                Landing page
              </Link>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
