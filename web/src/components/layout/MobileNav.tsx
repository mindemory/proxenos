"use client";

import { useEffect, useRef, useState } from "react";
import { Ellipsis, RefreshCw, X } from "lucide-react";

import { cn } from "@/lib/utils";

import { NAV_ITEMS, PRIMARY_MOBILE, type NavCounts, type NavItem, type View } from "./nav";

interface MobileNavProps {
  onNavigate: (view: View) => void;
  currentView: View;
  hasNew?: boolean;
  counts?: NavCounts;
  onRefresh: () => void;
}

const TAB = "relative flex min-w-0 flex-col items-center gap-0.5 rounded-xl py-1.5 text-[11px] tracking-tight transition-colors";

/** Bottom tab bar below the md breakpoint: four views and "More", a sheet with the rest. */
export function MobileNav({ onNavigate, currentView, hasNew = false, counts = {}, onRefresh }: MobileNavProps) {
  const [open, setOpen] = useState(false);
  const more = useRef<HTMLButtonElement>(null);
  const close = useRef<HTMLButtonElement>(null);
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
        <item.icon size={21} strokeWidth={2} />
        <span className="max-w-full truncate">{item.label}</span>
        {count ? (
          <span className="num absolute top-0.5 right-[18%] min-w-[16px] rounded-full bg-accent px-1 text-center text-[10px] font-medium leading-4 text-accent-ink">
            {count > 99 ? "99+" : count}
          </span>
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
          <Ellipsis size={21} strokeWidth={2} />
          <span>More</span>
          {badgeInMore && <span className="absolute top-1.5 right-[28%] h-2 w-2 rounded-full bg-accent" aria-hidden="true" />}
        </button>
      </nav>

      {open && (
        <div className="md:hidden fixed inset-0 z-[65]" role="dialog" aria-modal="true" aria-label="More views">
          <button className="absolute inset-0 bg-bg/70 backdrop-blur-sm fade-in" aria-label="Close" tabIndex={-1} onClick={() => setOpen(false)} />
          <div className="sheet-in absolute inset-x-0 bottom-0 rounded-t-3xl border-t border-line-strong bg-surface px-4 pt-3 pb-[max(1.25rem,env(safe-area-inset-bottom))]">
            <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-line-strong" aria-hidden="true" />
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-display text-xl text-ink">More</h2>
              <button ref={close} onClick={() => setOpen(false)} aria-label="Close" className="p-2 -m-2 rounded-full text-muted hover:text-ink">
                <X size={20} />
              </button>
            </div>
            <ul className="grid grid-cols-3 gap-2">
              {rest.map((item) => {
                const active = currentView === item.id;
                const count = counts[item.id];
                return (
                  <li key={item.id}>
                    <button
                      onClick={() => {
                        setOpen(false);
                        onNavigate(item.id);
                      }}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "relative w-full flex flex-col items-center gap-1.5 rounded-2xl border px-2 py-3.5 text-sm",
                        active ? "border-accent/40 bg-accent/10 text-accent" : "border-line text-ink hover:bg-surface-2",
                      )}
                    >
                      <item.icon size={22} strokeWidth={2} className={active ? "text-accent" : "text-muted"} />
                      {item.label}
                      {count ? (
                        <span className="num absolute top-2 right-2 min-w-[18px] rounded-full bg-accent px-1 text-center text-[10px] font-medium leading-[18px] text-accent-ink">
                          {count}
                        </span>
                      ) : item.id === "feed" && hasNew ? (
                        <span className="absolute top-2.5 right-2.5 h-2 w-2 rounded-full bg-accent" aria-label="New items" />
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
            <button
              onClick={() => {
                setOpen(false);
                onRefresh();
              }}
              className="mt-3 w-full flex items-center justify-center gap-2 rounded-2xl border border-line-strong py-3 text-sm text-ink hover:bg-surface-2"
            >
              <RefreshCw size={16} />
              Refresh everything
            </button>
          </div>
        </div>
      )}
    </>
  );
}
