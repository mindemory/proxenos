"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Brain, CornerDownLeft, DoorOpen, LoaderCircle, RefreshCw, Search, Users } from "lucide-react";

import { memorySourceIcon, memorySourceLabel } from "@/components/memory/sources";
import type { SourceIconComponent } from "@/components/SourceBadge";
import { sourceMeta } from "@/components/SourceBadge";
import { forgetEntered } from "@/lib/entry";
import { shortDate } from "@/lib/format";
import { plain } from "@/lib/memoryMarks";
import type { MemoryHit, MemorySearchResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

import { NAV_ITEMS, type NetworkTab, type View } from "./nav";

export interface CommandBoxProps {
  onNavigate: (view: View) => void;
  /** Go to the network graph and find a person there. */
  onFind: (query: string) => void;
  /** Go to a tab of the network view. */
  onNetworkTab: (tab: NetworkTab) => void;
  /** Open the memory view on a search, and on one hit's conversation when `id` is given. */
  onMemory: (query: string, id?: string) => void;
  onRefresh: () => void;
}

/** Memory hits shown under the commands. */
const MEMORY_HITS = 5;

type Section = "Find" | "Go to" | "Network" | "Actions" | "Memory";

interface Command {
  id: string;
  label: string;
  hint?: string;
  icon: SourceIconComponent;
  /** The icon's colour, for memory hits (their source's accent). */
  tint?: string;
  /** Extra words that should find it. */
  words?: string;
  section: Section;
  run: () => void;
}

const isTyping = (el: EventTarget | null) =>
  el instanceof HTMLElement && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));

/** What a hit says in one line: its title, else the words around the match. */
function hitLabel(hit: MemoryHit): string {
  return hit.title || plain(hit.snippet).replace(/\s+/g, " ").trim() || memorySourceLabel(hit.source);
}

/** Every typed word appears somewhere in the label or its extra words, in any order. */
function matches(c: Command, words: string[]): boolean {
  const hay = `${c.label} ${c.words ?? ""}`.toLowerCase();
  return words.every((w) => hay.includes(w));
}

/** The label with the typed words picked out. */
function Highlight({ text, words }: { text: string; words: string[] }) {
  if (words.length === 0) return <>{text}</>;
  const lower = text.toLowerCase();
  const marks = new Array<boolean>(text.length).fill(false);
  for (const w of words) {
    for (let i = lower.indexOf(w); i !== -1; i = lower.indexOf(w, i + w.length)) marks.fill(true, i, i + w.length);
  }
  const out: React.ReactNode[] = [];
  let i = 0;
  while (i < text.length) {
    let j = i;
    while (j < text.length && marks[j] === marks[i]) j++;
    const piece = text.slice(i, j);
    out.push(marks[i] ? <mark key={i} className="bg-transparent text-accent">{piece}</mark> : piece);
    i = j;
  }
  return <>{out}</>;
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="num inline-flex min-w-[1.375rem] items-center justify-center rounded-md border border-line-strong bg-surface-2 px-1 py-px text-[11px] text-muted">
      {children}
    </kbd>
  );
}

/** The command palette: jump to a view, run an action, look someone up in the network, or search memory. */
export function CommandBox({ onNavigate, onFind, onNetworkTab, onMemory, onRefresh }: CommandBoxProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [cursor, setCursor] = useState(0);
  const [found, setFound] = useState<{ q: string; hits: MemoryHit[] } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

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
        if (open) setOpen(false);
        else show();
      } else if (e.key === "/" && !isTyping(e.target) && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        show();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [show, open]);

  useEffect(() => {
    if (!open) return;
    input.current?.focus();
    const button = trigger.current;
    return () => button?.focus();
  }, [open]);

  // Memory is searched once typing has paused. An answer is shown only while it is for the text
  // in the box, and a slow or failed search just leaves the commands as they were.
  useEffect(() => {
    const q = text.trim();
    if (!open || q.length < 2) return;
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => {
      fetch(`/api/memory/search?${new URLSearchParams({ q, limit: String(MEMORY_HITS) })}`, {
        cache: "no-store",
        signal: ctrl.signal,
      })
        .then((res) => (res.ok ? (res.json() as Promise<MemorySearchResponse>) : null))
        .then((data) => setFound({ q, hits: data && data.indexed ? data.hits.slice(0, MEMORY_HITS) : [] }))
        .catch(() => {
          // A failed search shows no hits; one cancelled by more typing shows nothing yet.
          if (!ctrl.signal.aborted) setFound({ q, hits: [] });
        });
    }, 220);
    return () => {
      window.clearTimeout(timer);
      ctrl.abort();
    };
  }, [open, text]);

  const commands = useMemo<Command[]>(() => {
    const go: Command[] = NAV_ITEMS.map((item) => ({
      id: `go:${item.id}`,
      label: item.label,
      hint: "view",
      icon: item.icon,
      words: `go to open ${item.id}`,
      section: "Go to",
      run: () => onNavigate(item.id),
    }));
    const net = NAV_ITEMS.find((i) => i.id === "network")!;
    const tabs: Command[] = (
      [
        ["graph", "Network graph", "map connections"],
        ["list", "People list", "network table"],
        ["projects", "Project ideas", "network collaborations"],
        ["outreach", "Reach out", "network contact suggestions"],
      ] as const
    ).map(([tab, label, words]) => ({
      id: `net:${tab}`,
      label,
      icon: net.icon,
      words,
      section: "Network",
      run: () => onNetworkTab(tab),
    }));
    const actions: Command[] = [
      { id: "refresh", label: "Refresh everything", icon: RefreshCw, words: "reload sync update", section: "Actions", run: onRefresh },
      {
        id: "landing",
        label: "Back to the landing page",
        icon: DoorOpen,
        words: "proxenos home start welcome",
        section: "Actions",
        run: () => {
          forgetEntered();
          router.push("/");
        },
      },
    ];
    return [...go, ...tabs, ...actions];
  }, [onNavigate, onNetworkTab, onRefresh, router]);

  const typed = text.trim();
  const words = useMemo(() => typed.toLowerCase().split(/\s+/).filter(Boolean), [typed]);
  const searching = typed.length >= 2 && found?.q !== typed;

  const list = useMemo<Command[]>(() => {
    const matched = words.length ? commands.filter((c) => matches(c, words)) : commands;
    if (!typed) return matched;
    const find: Command = {
      id: "find",
      label: `Find “${typed}” in the network`,
      hint: "graph",
      icon: Users,
      section: "Find",
      run: () => onFind(typed),
    };
    if (typed.length < 2) return [...matched, find];
    const memory: Command[] = [
      {
        id: "memory",
        label: `Search memory for “${typed}”`,
        hint: "all results",
        icon: Brain,
        section: "Memory",
        run: () => onMemory(typed),
      },
      ...(found && found.q === typed ? found.hits : []).map<Command>((hit) => ({
        id: `mem:${hit.id}`,
        label: hitLabel(hit),
        hint: `${memorySourceLabel(hit.source)} · ${shortDate(hit.ts)}`,
        icon: memorySourceIcon(hit.source),
        tint: sourceMeta(hit.source).color,
        section: "Memory",
        run: () => onMemory(typed, hit.id),
      })),
    ];
    // Commands that match come first; with none, the searches lead.
    return matched.length ? [...matched, find, ...memory] : [...memory, find];
  }, [commands, words, typed, onFind, onMemory, found]);

  const active = Math.min(cursor, Math.max(0, list.length - 1));

  // Keep the active option in view as the cursor moves.
  useEffect(() => {
    if (!open) return;
    listRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  const run = (c: Command | undefined) => {
    if (!c) return;
    setOpen(false);
    c.run();
  };

  const onKey = (e: React.KeyboardEvent) => {
    const last = list.length - 1;
    if (e.key === "ArrowDown" || (e.key === "n" && e.ctrlKey)) {
      e.preventDefault();
      setCursor(active >= last ? 0 : active + 1);
    } else if (e.key === "ArrowUp" || (e.key === "p" && e.ctrlKey)) {
      e.preventDefault();
      setCursor(active <= 0 ? last : active - 1);
    } else if (e.key === "Home" && list.length) {
      e.preventDefault();
      setCursor(0);
    } else if (e.key === "End" && list.length) {
      e.preventDefault();
      setCursor(last);
    } else if (e.key === "Enter") {
      e.preventDefault();
      run(list[active]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      if (text) setText("");
      else setOpen(false);
    } else if (e.key === "Tab") {
      // Focus stays in the box while it's open.
      e.preventDefault();
    }
  };

  return (
    <>
      <button
        ref={trigger}
        onClick={show}
        aria-label="Command palette: jump to a view, find a person, or search your memory"
        aria-haspopup="dialog"
        className="group flex h-9 min-w-0 max-w-md flex-1 items-center gap-2.5 rounded-full border border-line-strong bg-surface px-3.5 text-left text-sm text-muted shadow-card transition-colors hover:border-accent/40 hover:text-ink"
      >
        <Search size={15} className="flex-shrink-0" />
        <span className="min-w-0 flex-1 truncate">
          <span className="sm:hidden">Search</span>
          <span className="hidden sm:inline">Jump, find someone, or search memory</span>
        </span>
        <span className="hidden items-center gap-1 sm:flex">
          <Kbd>⌘</Kbd>
          <Kbd>K</Kbd>
        </span>
      </button>

      {open && (
        <div className="fixed inset-0 z-[70]" role="dialog" aria-modal="true" aria-label="Command palette">
          <button className="fade-in absolute inset-0 bg-bg/75 backdrop-blur-sm" aria-label="Close" tabIndex={-1} onClick={() => setOpen(false)} />
          <div className="sheet-in relative mx-auto mt-[8vh] flex max-h-[80dvh] w-[min(94vw,38rem)] flex-col overflow-hidden rounded-2xl border border-line-strong bg-surface shadow-pop">
            <div className="flex items-center gap-3 border-b border-line px-4">
              {searching ? (
                <LoaderCircle size={17} className="flex-shrink-0 animate-spin text-muted motion-reduce:animate-none" aria-hidden="true" />
              ) : (
                <Search size={17} className="flex-shrink-0 text-muted" aria-hidden="true" />
              )}
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
                aria-autocomplete="list"
                aria-activedescendant={list[active] ? `cmd-${list[active].id}` : undefined}
                placeholder="Go to a view, find someone, or search your memory"
                autoComplete="off"
                spellCheck={false}
                className="h-14 w-full bg-transparent text-base text-ink placeholder:text-muted focus:outline-none"
              />
              <span className="hidden sm:block">
                <Kbd>esc</Kbd>
              </span>
            </div>
            <ul ref={listRef} id="command-list" role="listbox" aria-label="Commands" className="min-h-0 flex-1 overflow-y-auto overscroll-contain py-2">
              {list.length === 0 && <li className="px-4 py-6 text-center text-sm text-muted">Nothing matches.</li>}
              {list.map((c, i) => {
                const selected = i === active;
                const heading = c.section !== list[i - 1]?.section;
                return (
                  <li key={c.id} role="presentation">
                    {heading && (
                      <span className="smallcaps block px-4 pb-1.5 pt-3 text-faint" aria-hidden="true">
                        {c.section}
                      </span>
                    )}
                    <div
                      id={`cmd-${c.id}`}
                      role="option"
                      aria-selected={selected}
                      data-index={i}
                      onClick={() => run(c)}
                      onMouseMove={() => cursor !== i && setCursor(i)}
                      className={cn(
                        "relative mx-2 flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 text-sm",
                        selected ? "bg-surface-2 text-ink" : "text-ink/90",
                      )}
                    >
                      {selected && <span className="absolute left-0 top-2 bottom-2 w-[3px] rounded-r-full bg-accent" aria-hidden="true" />}
                      <span
                        className={cn(
                          "flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg border",
                          selected ? "border-accent/30 bg-accent/10" : "border-line bg-bg/40",
                        )}
                        style={c.tint ? { color: c.tint } : undefined}
                      >
                        <c.icon size={15} className={c.tint ? undefined : selected ? "text-accent" : "text-muted"} aria-hidden="true" />
                      </span>
                      <span className="min-w-0 flex-1 truncate">
                        <Highlight text={c.label} words={c.section === "Memory" || c.section === "Find" ? [] : words} />
                      </span>
                      {c.hint && <span className="hidden flex-shrink-0 text-xs text-muted sm:inline">{c.hint}</span>}
                      {selected && <CornerDownLeft size={14} className="flex-shrink-0 text-muted" aria-hidden="true" />}
                    </div>
                  </li>
                );
              })}
              {searching && (
                <li role="presentation" className="px-5 py-2 text-xs text-muted">
                  Searching memory…
                </li>
              )}
            </ul>
            <div className="hidden items-center gap-4 border-t border-line px-4 py-2.5 text-xs text-muted sm:flex">
              <span className="inline-flex items-center gap-1.5">
                <Kbd>↑</Kbd>
                <Kbd>↓</Kbd> move
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Kbd>↵</Kbd> open
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Kbd>esc</Kbd> {text ? "clear" : "close"}
              </span>
              <span className="ml-auto">
                Type two letters or more to search memory
              </span>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
