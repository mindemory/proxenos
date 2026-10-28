"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CornerDownLeft, RefreshCw, Search, Users, type LucideIcon } from "lucide-react";

import type { NetworkTab } from "@/components/views/Network";
import { cn } from "@/lib/utils";

import { NAV_ITEMS, type View } from "./nav";

export interface CommandBoxProps {
  onNavigate: (view: View) => void;
  /** Go to the network graph and find a person there. */
  onFind: (query: string) => void;
  /** Go to a tab of the network view. */
  onNetworkTab: (tab: NetworkTab) => void;
  onRefresh: () => void;
}

interface Command {
  id: string;
  label: string;
  hint?: string;
  icon: LucideIcon;
  /** Extra words that should find it. */
  words?: string;
  run: () => void;
}

const isTyping = (el: EventTarget | null) =>
  el instanceof HTMLElement && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));

/** The command box in the top bar: jump to a view, run an action, or look someone up in the network. */
export function CommandBox({ onNavigate, onFind, onNetworkTab, onRefresh }: CommandBoxProps) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [cursor, setCursor] = useState(0);
  const trigger = useRef<HTMLButtonElement>(null);
  const input = useRef<HTMLInputElement>(null);

  const show = useCallback(() => {
    setText("");
    setCursor(0);
    setOpen(true);
  }, []);

  // ⌘K or Ctrl+K from anywhere, and "/" when not typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        show();
      } else if (e.key === "/" && !isTyping(e.target) && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        show();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [show]);

  useEffect(() => {
    if (!open) return;
    input.current?.focus();
    const button = trigger.current;
    return () => button?.focus();
  }, [open]);

  const commands = useMemo<Command[]>(() => {
    const go: Command[] = NAV_ITEMS.map((item) => ({
      id: `go:${item.id}`,
      label: `Go to ${item.label}`,
      icon: item.icon,
      run: () => onNavigate(item.id),
    }));
    const net = NAV_ITEMS.find((i) => i.id === "network")!;
    const tabs: Command[] = (
      [
        ["graph", "Network graph", "map connections"],
        ["list", "Network list", "people table"],
        ["projects", "Network projects", "ideas collaborations"],
        ["outreach", "Reach out", "network contact suggestions"],
      ] as const
    ).map(([tab, label, words]) => ({ id: `net:${tab}`, label: `Open ${label}`, icon: net.icon, words, run: () => onNetworkTab(tab) }));
    const actions: Command[] = [
      { id: "refresh", label: "Refresh everything", icon: RefreshCw, words: "reload sync update", run: onRefresh },
    ];
    return [...go, ...tabs, ...actions];
  }, [onNavigate, onNetworkTab, onRefresh]);

  const q = text.trim().toLowerCase();
  const list = useMemo<Command[]>(() => {
    const matches = q ? commands.filter((c) => `${c.label} ${c.words ?? ""}`.toLowerCase().includes(q)) : commands;
    if (!q) return matches;
    const find: Command = {
      id: "find",
      label: `Find “${text.trim()}” in the network`,
      hint: "graph",
      icon: Users,
      run: () => onFind(text.trim()),
    };
    return [find, ...matches];
  }, [commands, q, text, onFind]);

  const run = (c: Command | undefined) => {
    if (!c) return;
    setOpen(false);
    c.run();
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((c) => (c + 1) % list.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) => (c - 1 + list.length) % list.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      run(list[Math.min(cursor, list.length - 1)]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
    }
  };

  return (
    <>
      <button
        ref={trigger}
        onClick={show}
        aria-label="Jump to a view or find a person"
        aria-haspopup="dialog"
        className="group flex h-9 min-w-0 flex-1 max-w-md items-center gap-2.5 rounded-full border border-line-strong bg-surface px-3.5 text-left text-sm text-muted transition-colors hover:border-accent/40 hover:text-ink"
      >
        <Search size={15} className="flex-shrink-0" />
        <span className="min-w-0 flex-1 truncate">
          <span className="sm:hidden">Jump or find</span>
          <span className="hidden sm:inline">Jump to a view or find someone</span>
        </span>
        <kbd className="num hidden sm:inline rounded-md border border-line-strong px-1.5 py-0.5 text-[11px] text-muted group-hover:text-ink">⌘K</kbd>
      </button>

      {open && (
        <div className="fixed inset-0 z-[70]" role="dialog" aria-modal="true" aria-label="Command box">
          <button className="absolute inset-0 bg-bg/70 backdrop-blur-sm fade-in" aria-label="Close" tabIndex={-1} onClick={() => setOpen(false)} />
          <div className="sheet-in relative mx-auto mt-[10vh] w-[min(92vw,34rem)] overflow-hidden rounded-2xl border border-line-strong bg-surface shadow-pop">
            <div className="flex items-center gap-3 border-b border-line px-4">
              <Search size={16} className="text-muted flex-shrink-0" />
              <input
                ref={input}
                value={text}
                onChange={(e) => {
                  setText(e.target.value);
                  setCursor(0);
                }}
                onKeyDown={onKey}
                role="combobox"
                aria-expanded="true"
                aria-controls="command-list"
                aria-activedescendant={list[cursor] ? `cmd-${list[cursor].id}` : undefined}
                placeholder="Go to a view, or type a name to find in the network"
                autoComplete="off"
                spellCheck={false}
                className="h-12 w-full bg-transparent text-[15px] text-ink placeholder:text-muted/80 focus:outline-none"
              />
            </div>
            <ul id="command-list" role="listbox" className="max-h-[50vh] overflow-y-auto py-1.5">
              {list.length === 0 && <li className="px-4 py-3 text-sm text-muted">Nothing matches.</li>}
              {list.map((c, i) => (
                <li key={c.id} id={`cmd-${c.id}`} role="option" aria-selected={i === cursor}>
                  <button
                    onClick={() => run(c)}
                    onMouseEnter={() => setCursor(i)}
                    tabIndex={-1}
                    className={cn("flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm", i === cursor ? "bg-surface-2 text-ink" : "text-ink/90")}
                  >
                    <c.icon size={16} className={i === cursor ? "text-accent" : "text-muted"} />
                    <span className="min-w-0 flex-1 truncate">{c.label}</span>
                    {c.hint && <span className="text-xs text-muted">{c.hint}</span>}
                    {i === cursor && <CornerDownLeft size={14} className="text-muted flex-shrink-0" />}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </>
  );
}
