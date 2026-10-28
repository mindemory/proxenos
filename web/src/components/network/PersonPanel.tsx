"use client";

import { useState } from "react";
import { X } from "lucide-react";

import { SourceBadge } from "@/components/SourceBadge";
import { formatDateTime, plural, shortDate } from "@/lib/format";
import type { GraphModel } from "@/lib/graph";
import type { NetworkResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

import { Actions, Citation, KIND_LABEL_ONE, Label, RELATION_LABEL, RELATION_STYLE, type OnReact } from "./parts";

const SHOWN = 8;

interface PersonPanelProps {
  model: GraphModel;
  idx: number;
  data: NetworkResponse;
  flashId: string | null;
  /** The group whose members are lit in the graph, if any. */
  groupFocus: number | null;
  onSelect: (idx: number) => void;
  onGroup: (groupIndex: number | null) => void;
  onClose: () => void;
  onReact: OnReact;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <Label>{title}</Label>
      {children}
    </section>
  );
}

/** One person: who they are, what the twin suggests for them, who they're tied to and why. */
export function PersonPanel({ model, idx, data, flashId, groupFocus, onSelect, onGroup, onClose, onReact }: PersonPanelProps) {
  const [allTies, setAllTies] = useState(false);
  const [allGroups, setAllGroups] = useState(false);
  const node = model.nodes[idx];
  const p = node.person;
  const style = RELATION_STYLE[p.relation];

  const ties = model.adj[idx];
  const groups = model.nodeGroups[idx];
  const outreach = data.ideas.outreach.filter((o) => o.person_id === p.id);
  const projects = data.ideas.projects.filter((x) => x.people.includes(p.id));

  return (
    <div className="h-full overflow-y-auto overscroll-contain">
      <div className="sticky top-0 z-10 bg-surface/95 backdrop-blur px-4 pt-4 pb-3 border-b border-line flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="font-display text-2xl leading-tight text-ink break-words">{p.name}</h2>
          <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-sm text-muted">
            <span className={cn("inline-flex items-center gap-1.5", style.text)}>
              <span className={cn("w-2 h-2 rounded-full", style.dot)} />
              {RELATION_LABEL[p.relation]}
            </span>
            {p.org && <span className="break-words min-w-0">{p.org}</span>}
          </div>
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="p-1.5 -m-1 rounded-lg text-muted hover:text-ink hover:bg-surface-2"
        >
          <X size={18} />
        </button>
      </div>

      <div className="p-4 space-y-5">
        <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1 text-sm text-muted">
          <span>
            <span className="num text-ink">{p.interactions.toLocaleString()}</span> interactions
          </span>
          <span>
            <span className="num text-ink">{ties.length}</span> {ties.length === 1 ? "tie" : "ties"}
          </span>
          {p.last_seen && shortDate(p.last_seen, data.now) && (
            <span title={formatDateTime(p.last_seen)}>
              last seen <span className="num text-ink">{shortDate(p.last_seen, data.now)}</span>
            </span>
          )}
        </div>

        {p.context && <p className="text-sm text-ink/90 leading-relaxed break-words">{p.context}</p>}

        {(p.sources.length > 0 || p.topics.length > 0) && (
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            {[...new Set(p.sources.map((s) => s.split("/")[0]))].map((s) => (
              <SourceBadge key={s} kind={s} />
            ))}
            {p.topics.map((t) => (
              <span key={t} className="rounded-md border border-line px-1.5 py-0.5 text-muted break-all">
                #{t}
              </span>
            ))}
          </div>
        )}

        {outreach.map((o) => (
          <section
            key={o.id}
            className={cn("space-y-3 rounded-xl", flashId === o.id && "row-flash", o.action === "not_me" && "opacity-70")}
          >
            <Label>Suggested outreach</Label>
            {o.ask && <Citation label={o.channel ? `The ask, by ${o.channel.replace("_", " ")}` : "The ask"} small>{o.ask}</Citation>}
            {o.why && <p className="text-sm text-muted leading-relaxed break-words">{o.why}</p>}
            <Actions item={o} now={data.now} onReact={onReact} />
          </section>
        ))}

        {projects.length > 0 && (
          <Section title="In project ideas">
            <ul className="space-y-1 text-sm text-ink/90">
              {projects.map((x) => (
                <li key={x.id} className="break-words">
                  {x.title}
                </li>
              ))}
            </ul>
          </Section>
        )}

        {groups.length > 0 && (
          <Section title={`Shared contexts · ${groups.length}`}>
            <ul className="space-y-1">
              {(allGroups ? groups : groups.slice(0, SHOWN)).map((gi) => {
                const g = model.groups[gi];
                const on = groupFocus === gi;
                return (
                  <li key={g.group.id}>
                    <button
                      onClick={() => onGroup(on ? null : gi)}
                      aria-pressed={on}
                      title={on ? "Stop highlighting these people" : "Light up everyone in this one"}
                      className={cn(
                        "w-full text-left rounded-lg border px-2.5 py-1.5 text-sm transition-colors",
                        on ? "border-accent/40 bg-accent/10 text-accent" : "border-line text-ink/90 hover:bg-surface-2",
                      )}
                    >
                      <span className="block break-words">{g.group.name}</span>
                      <span className="block text-xs text-muted">
                        {KIND_LABEL_ONE[g.group.kind]} · {plural(g.members.length, "person", "people")}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
            {groups.length > SHOWN && (
              <button onClick={() => setAllGroups((v) => !v)} className="text-xs text-accent hover:underline underline-offset-4">
                {allGroups ? "Show fewer" : `Show all ${groups.length}`}
              </button>
            )}
          </Section>
        )}

        <Section title={`Connections · ${ties.length}`}>
          {ties.length === 0 ? (
            <p className="text-sm text-muted leading-relaxed">
              No ties to anyone else in the graph: no group or organization in common with the people drawn here.
            </p>
          ) : (
            <>
              <ul className="space-y-1">
                {(allTies ? ties : ties.slice(0, SHOWN)).map(({ other, edge }) => {
                  const e = model.edges[edge];
                  const o = model.nodes[other].person;
                  return (
                    <li key={other}>
                      <button
                        onClick={() => onSelect(other)}
                        className="w-full text-left rounded-lg border border-line px-2.5 py-1.5 hover:bg-surface-2 transition-colors"
                        title={e.contexts.join("\n")}
                      >
                        <span className="flex items-baseline justify-between gap-3">
                          <span className="min-w-0 break-words text-sm text-ink">{o.name}</span>
                          <span className="num text-xs text-muted flex-shrink-0" title={plural(e.weight, "shared context")}>
                            ×{e.weight}
                          </span>
                        </span>
                        {e.contexts.length > 0 && (
                          <span className="block text-xs text-muted line-clamp-2 break-words">{e.contexts.join(" · ")}</span>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
              {ties.length > SHOWN && (
                <button onClick={() => setAllTies((v) => !v)} className="text-xs text-accent hover:underline underline-offset-4">
                  {allTies ? "Show fewer" : `Show all ${ties.length}`}
                </button>
              )}
            </>
          )}
        </Section>
      </div>
    </div>
  );
}
