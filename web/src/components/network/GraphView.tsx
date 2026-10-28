"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Maximize2, Minus, Network as NetworkIcon, Plus, Search, SlidersHorizontal, X } from "lucide-react";

import { Command, EmptyState } from "@/components/EmptyState";
import type { NetworkTab } from "@/components/views/Network";
import { plural } from "@/lib/format";
import { applyFilters, buildGraph, fold, searchNodes, type Filters } from "@/lib/graph";
import type { HoverInfo } from "@/lib/graphEngine";
import { useBox, useMedia } from "@/lib/hooks";
import { GROUP_KINDS, RELATIONS, type GroupKind, type NetworkResponse, type Relation } from "@/lib/types";
import { cn } from "@/lib/utils";

import { GraphCanvas, type GraphHandle } from "./GraphCanvas";
import { KIND_LABEL, RELATION_LABEL, RELATION_STYLE, type OnReact } from "./parts";
import { PersonPanel } from "./PersonPanel";

const PANEL_WIDTH = 360;
const SHEET_FRACTION = 0.46;

interface GraphViewProps {
  data: NetworkResponse;
  flashId: string | null;
  onReact: OnReact;
  /** A name to find, sent from the command box. A new `nonce` finds it again. */
  find?: { q: string; nonce: number } | null;
  /** Called once `find` is used, so the page can drop it and a later visit doesn't find it again. */
  onFound?: () => void;
  /** Switch tab, for "see the list". */
  onTab?: (tab: NetworkTab) => void;
}

function toggled<T>(set: ReadonlySet<T>, value: T): Set<T> {
  const next = new Set(set);
  if (!next.delete(value)) next.add(value);
  return next;
}

function Chip({
  on,
  onClick,
  children,
  title,
}: {
  on: boolean;
  onClick: () => void;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={on}
      title={title}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[13px] transition-colors whitespace-nowrap",
        on ? "border-accent/40 bg-accent/10 text-accent" : "border-line-strong text-muted hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

function IconButton({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      title={label}
      className="w-9 h-9 flex items-center justify-center text-muted hover:text-ink hover:bg-surface-2 transition-colors"
    >
      {children}
    </button>
  );
}

export function GraphView({ data, flashId, onReact, find, onFound, onTab }: GraphViewProps) {
  const model = useMemo(() => buildGraph(data.people, data.now), [data.people, data.now]);
  const handle = useRef<GraphHandle>(null);
  const [boxRef, box] = useBox<HTMLDivElement>();
  const desktop = useMedia("(min-width: 768px)");

  const [selected, setSelected] = useState<number | null>(null);
  const [groupFocus, setGroupFocus] = useState<number | null>(null);
  const [hover, setHover] = useState<HoverInfo | null>(null);
  const [relations, setRelations] = useState<ReadonlySet<Relation>>(new Set());
  const [kinds, setKinds] = useState<ReadonlySet<GroupKind>>(new Set());
  const [hideUnconnected, setHideUnconnected] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const [seenFind, setSeenFind] = useState(0);
  const [focusReq, setFocusReq] = useState<{ idx: number; n: number } | null>(null);

  const filters = useMemo<Filters>(() => ({ relations, kinds, hideUnconnected }), [relations, kinds, hideUnconnected]);
  const visibility = useMemo(() => applyFilters(model, filters), [model, filters]);
  const results = useMemo(() => searchNodes(model, text), [model, text]);
  const highlight = useMemo(
    () => (groupFocus === null ? null : new Set(model.groups[groupFocus]?.members ?? [])),
    [model, groupFocus],
  );

  const counts = useMemo(() => {
    const byRelation: Record<Relation, number> = { met: 0, know_of: 0, to_read: 0 };
    for (const n of model.nodes) byRelation[n.person.relation]++;
    const byKind = Object.fromEntries(GROUP_KINDS.map((k) => [k, 0])) as Record<GroupKind, number>;
    for (const g of model.groups) byKind[g.group.kind]++;
    return { byRelation, byKind };
  }, [model]);

  const shownNodes = visibility.node.filter(Boolean).length;
  const shownEdges = visibility.edge.filter(Boolean).length;
  const filtered = relations.size > 0 || kinds.size > 0 || hideUnconnected;

  /** Select someone, make sure they're on screen, and bring them to the middle. */
  const choose = (idx: number) => {
    if (!visibility.node[idx]) {
      setRelations(new Set());
      setKinds(new Set());
      setHideUnconnected(false);
    }
    setSelected(idx);
    setGroupFocus(null);
    // The panel opens next render; centre in what it will leave.
    handle.current?.focus(idx, desktop ? { right: PANEL_WIDTH } : { bottom: Math.round(box.h * SHEET_FRACTION) });
  };

  // The command box sent a name: put it in the search box and go to the best match.
  if (find && find.nonce !== seenFind) {
    setSeenFind(find.nonce);
    setText(find.q);
    setOpen(false);
    const [best] = searchNodes(model, find.q, 1);
    if (best !== undefined) {
      setSelected(best);
      setGroupFocus(null);
      setRelations(new Set());
      setKinds(new Set());
      setHideUnconnected(false);
      setFocusReq({ idx: best, n: find.nonce });
    }
  }

  // The canvas has its engine by the time this runs, so the move can start.
  useEffect(() => {
    if (focusReq) handle.current?.focus(focusReq.idx);
  }, [focusReq]);
  useEffect(() => {
    if (find) onFound?.();
  }, [find, onFound]);

  if (!data.people.exists) {
    return (
      <EmptyState icon={NetworkIcon} title="No people index yet" command="twin clone network --people-only">
        The network clone indexes the people in your messages, mentions and reading, and who shares a chat, a thread,
        a paper or an employer with whom.
      </EmptyState>
    );
  }
  if (model.nodes.length === 0) {
    return (
      <EmptyState icon={NetworkIcon} title="No one to draw" command="twin clone network --people-only">
        The people index is empty. Run the network clone after syncing your sources.
      </EmptyState>
    );
  }

  const pick = (idx: number) => {
    choose(idx);
    setOpen(false);
    setText(model.nodes[idx].person.name);
  };

  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" && results.length) {
      e.preventDefault();
      setOpen(true);
      setCursor((c) => (c + 1) % results.length);
    } else if (e.key === "ArrowUp" && results.length) {
      e.preventDefault();
      setCursor((c) => (c - 1 + results.length) % results.length);
    } else if (e.key === "Enter" && results.length) {
      e.preventDefault();
      pick(results[Math.min(cursor, results.length - 1)]);
    } else if (e.key === "Escape") {
      if (open) setOpen(false);
      else setText("");
    }
  };

  const panelOpen = selected !== null;
  const insetRight = panelOpen && desktop ? PANEL_WIDTH : 0;
  const insetBottom = panelOpen && !desktop ? Math.round(box.h * SHEET_FRACTION) : 0;
  const hoverNode = hover ? model.nodes[hover.idx] : null;
  const indexMatches =
    text.trim() && results.length === 0
      ? data.people.list.filter((p) => fold(p.name).includes(fold(text.trim()))).length
      : 0;

  return (
    <div className="flex flex-col h-[calc(100dvh-11rem)] md:h-[calc(100dvh-6.75rem)] min-h-[30rem]">
      <div className="px-3 sm:px-5 pt-3 pb-2.5 space-y-2.5 border-b border-line">
        <div className="flex items-center gap-2">
          <div className="relative flex-1 min-w-0 sm:max-w-sm">
            <label className="block">
              <span className="sr-only">Find a person in the graph</span>
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted pointer-events-none" />
              <input
                type="text"
                role="combobox"
                aria-expanded={open && text.trim() !== ""}
                aria-controls="graph-results"
                aria-autocomplete="list"
                value={text}
                onChange={(e) => {
                  setText(e.target.value);
                  setCursor(0);
                  setOpen(true);
                }}
                onFocus={() => setOpen(true)}
                onBlur={() => window.setTimeout(() => setOpen(false), 120)}
                onKeyDown={onKey}
                placeholder="Find someone"
                autoComplete="off"
                spellCheck={false}
                className="w-full rounded-full border border-line-strong bg-surface pl-8 pr-8 py-1.5 text-sm text-ink placeholder:text-muted/80"
              />
            </label>
            {text && (
              <button
                onClick={() => {
                  setText("");
                  setOpen(false);
                }}
                aria-label="Clear search"
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-full text-muted hover:text-ink"
              >
                <X size={13} />
              </button>
            )}
            {open && text.trim() !== "" && (
              <div
                id="graph-results"
                role="listbox"
                className="absolute left-0 right-0 top-full mt-1.5 z-30 rounded-xl border border-line-strong bg-surface shadow-pop overflow-hidden"
              >
                {results.length > 0 ? (
                  results.map((idx, i) => {
                    const p = model.nodes[idx].person;
                    return (
                      <button
                        key={idx}
                        role="option"
                        aria-selected={i === cursor}
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => pick(idx)}
                        onMouseEnter={() => setCursor(i)}
                        className={cn("w-full text-left px-3 py-2 flex items-center gap-2.5", i === cursor && "bg-surface-2")}
                      >
                        <span className={cn("w-2 h-2 rounded-full flex-shrink-0", RELATION_STYLE[p.relation].dot)} />
                        <span className="min-w-0">
                          <span className="block text-sm text-ink truncate">{p.name}</span>
                          {(p.org || p.context) && <span className="block text-xs text-muted truncate">{p.org ?? p.context}</span>}
                        </span>
                      </button>
                    );
                  })
                ) : (
                  <p className="px-3 py-2.5 text-sm text-muted leading-relaxed">
                    No one in the graph by that name.
                    {indexMatches > 0 && (
                      <>
                        {" "}
                        {plural(indexMatches, "person", "people")} in the index match, outside the{" "}
                        <span className="num">{model.nodes.length}</span> drawn.{" "}
                        <button
                          onMouseDown={(e) => e.preventDefault()}
                          onClick={() => onTab?.("list")}
                          className="text-accent hover:underline underline-offset-4"
                        >
                          Open the list
                        </button>
                      </>
                    )}
                  </p>
                )}
              </div>
            )}
          </div>

          <button
            onClick={() => setFiltersOpen((v) => !v)}
            aria-expanded={filtersOpen}
            className={cn(
              "sm:hidden inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[13px]",
              filtered ? "border-accent/40 text-accent" : "border-line-strong text-muted",
            )}
          >
            <SlidersHorizontal size={14} />
            Filters
          </button>

          <p className="hidden lg:block ml-auto text-sm text-muted whitespace-nowrap">
            <span className="num text-ink">{shownNodes.toLocaleString()}</span> of{" "}
            <span className="num">{model.nodes.length.toLocaleString()}</span> people ·{" "}
            <span className="num text-ink">{shownEdges.toLocaleString()}</span> ties
          </p>
        </div>

        <div className={cn("flex-wrap items-center gap-1.5", filtersOpen ? "flex" : "hidden sm:flex")}>
          {RELATIONS.map((r) => (
            <Chip key={r} on={relations.has(r)} onClick={() => setRelations((cur) => toggled(cur, r))}>
              <span className={cn("w-2 h-2 rounded-full", RELATION_STYLE[r].dot)} />
              {RELATION_LABEL[r]} <span className="num">{counts.byRelation[r]}</span>
            </Chip>
          ))}
          <span className="hidden sm:block w-px h-5 bg-line-strong mx-1" aria-hidden="true" />
          {GROUP_KINDS.filter((k) => counts.byKind[k] > 0).map((k) => (
            <Chip
              key={k}
              on={kinds.has(k)}
              onClick={() => setKinds((cur) => toggled(cur, k))}
              title={`Only ties made by ${KIND_LABEL[k].toLowerCase()}`}
            >
              {KIND_LABEL[k]} <span className="num">{counts.byKind[k]}</span>
            </Chip>
          ))}
          <span className="hidden sm:block w-px h-5 bg-line-strong mx-1" aria-hidden="true" />
          <Chip on={hideUnconnected} onClick={() => setHideUnconnected((v) => !v)} title="Hide people with no tie on screen">
            Hide unconnected
          </Chip>
          {filtered && (
            <button
              onClick={() => {
                setRelations(new Set());
                setKinds(new Set());
                setHideUnconnected(false);
              }}
              className="text-[13px] text-accent px-2 hover:underline underline-offset-4"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      <div ref={boxRef} className="relative flex-1 min-h-0 overflow-hidden">
        <GraphCanvas
          ref={handle}
          model={model}
          filters={filters}
          selected={selected}
          highlight={highlight}
          insetRight={insetRight}
          insetBottom={insetBottom}
          label={`Network graph of ${model.nodes.length} people and ${model.edges.length} ties. The List tab has the same people as text.`}
          onSelect={(idx) => {
            setSelected(idx);
            setGroupFocus(null);
          }}
          onHover={setHover}
        />

        {model.edges.length === 0 && (
          <p className="absolute left-4 top-3 right-4 sm:right-auto sm:max-w-sm rounded-xl border border-line bg-surface/90 px-3 py-2 text-sm text-muted leading-relaxed">
            No ties in this index yet. <Command>twin clone network --people-only</Command> adds who shares a chat, a thread, a
            paper or an employer.
          </p>
        )}

        <div className="absolute left-3 bottom-3 flex flex-col rounded-xl border border-line-strong bg-surface/90 backdrop-blur overflow-hidden divide-y divide-line">
          <IconButton label="Zoom in" onClick={() => handle.current?.zoomBy(1.4)}>
            <Plus size={16} />
          </IconButton>
          <IconButton label="Zoom out" onClick={() => handle.current?.zoomBy(1 / 1.4)}>
            <Minus size={16} />
          </IconButton>
          <IconButton label="Fit everyone on screen" onClick={() => handle.current?.fit()}>
            <Maximize2 size={15} />
          </IconButton>
        </div>

        <p className="hidden md:block absolute left-16 bottom-3.5 text-xs text-muted/80 pointer-events-none">
          Scroll to zoom · drag to pan · drag a node to move it
        </p>

        {hover && hoverNode && !(hover.idx === selected) && (
          <div
            className="pointer-events-none absolute z-20 w-64 rounded-xl border border-line-strong bg-surface-2/95 backdrop-blur px-3 py-2 shadow-pop fade-in"
            style={{
              left: Math.max(8, Math.min(hover.x + 14, box.w - 264 - insetRight)),
              top: Math.max(8, Math.min(hover.y + 16, box.h - 110)),
            }}
          >
            <div className="font-display text-base leading-snug text-ink break-words">{hoverNode.person.name}</div>
            <div className="mt-0.5 flex items-center gap-2 text-xs text-muted">
              <span className={cn("inline-flex items-center gap-1.5", RELATION_STYLE[hoverNode.person.relation].text)}>
                <span className={cn("w-1.5 h-1.5 rounded-full", RELATION_STYLE[hoverNode.person.relation].dot)} />
                {RELATION_LABEL[hoverNode.person.relation]}
              </span>
              {hoverNode.person.org && <span className="truncate">{hoverNode.person.org}</span>}
            </div>
            {hoverNode.person.context && (
              <p className="mt-1 text-xs text-ink/80 leading-snug line-clamp-3 break-words">{hoverNode.person.context}</p>
            )}
          </div>
        )}

        {selected !== null && model.nodes[selected] && (
          <aside
            aria-label="Person"
            className="absolute z-20 bg-surface border-line shadow-pop inset-x-0 bottom-0 h-[46%] rounded-t-2xl border-t sheet-in md:inset-x-auto md:top-0 md:right-0 md:h-auto md:w-[360px] md:rounded-none md:border-t-0 md:border-l md:panel-in"
          >
            <PersonPanel
              key={selected}
              model={model}
              idx={selected}
              data={data}
              flashId={flashId}
              groupFocus={groupFocus}
              onSelect={choose}
              onGroup={setGroupFocus}
              onClose={() => {
                setSelected(null);
                setGroupFocus(null);
              }}
              onReact={onReact}
            />
          </aside>
        )}
      </div>
    </div>
  );
}
