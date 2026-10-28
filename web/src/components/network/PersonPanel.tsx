"use client";

import { useMemo, useState } from "react";
import { EyeOff, Search, Split, Users, X } from "lucide-react";

import { SourceBadge } from "@/components/SourceBadge";
import { clusterVar } from "@/lib/clusters";
import { formatDateTime, plural, shortDate } from "@/lib/format";
import { searchNodes, type GraphModel } from "@/lib/graph";
import type { Cluster, NetworkResponse, PeopleEdit, PeopleEditResult } from "@/lib/types";
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
  clusters: ReadonlyMap<number, Cluster>;
  /** Say who this person is: the same as another, not the same as another or a name, or hidden. */
  onEdit?: (action: PeopleEdit, other?: { id: string } | { name: string }) => Promise<PeopleEditResult>;
  /** Rebuild the index now, for an edit that was saved without one. */
  onRefresh?: () => Promise<PeopleEditResult>;
}

type Target = { idx: number } | { name: string };

const EDIT_LABEL: Record<PeopleEdit, string> = {
  same: "Same person as…",
  different: "Not the same as…",
  hide: "Hide",
};

/** Merge, split or hide: written to aliases.json, and the index is rebuilt with it. */
function WhoIsThis({
  model,
  idx,
  onEdit,
  onRefresh,
}: {
  model: GraphModel;
  idx: number;
  onEdit: NonNullable<PersonPanelProps["onEdit"]>;
  onRefresh?: PersonPanelProps["onRefresh"];
}) {
  const [mode, setMode] = useState<PeopleEdit | null>(null);
  const [query, setQuery] = useState("");
  const [target, setTarget] = useState<Target | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ text: string; retry: boolean } | null>(null);
  const p = model.nodes[idx].person;
  const results = useMemo(
    () => (mode === "same" || mode === "different" ? searchNodes(model, query, 7).filter((i) => i !== idx) : []),
    [model, query, mode, idx],
  );

  const reset = () => {
    setMode(null);
    setQuery("");
    setTarget(null);
  };
  const save = async () => {
    if (!mode || (mode !== "hide" && !target)) return;
    setBusy(true);
    setNote(null);
    const other = target === null ? undefined : "idx" in target ? { id: model.nodes[target.idx].id } : { name: target.name };
    const result = await onEdit(mode, other);
    setBusy(false);
    reset();
    if (!result.saved) setNote({ text: "Couldn't save that. Nothing was changed.", retry: false });
    else if (!result.rebuilt) setNote({ text: `Saved, applies on the next refresh. ${result.message}`, retry: !!onRefresh });
  };
  const refresh = async () => {
    if (!onRefresh) return;
    setBusy(true);
    const result = await onRefresh();
    setBusy(false);
    setNote(result.rebuilt ? null : { text: result.message || "The rebuild didn't finish.", retry: true });
  };
  const otherName = target === null ? "" : "idx" in target ? model.nodes[target.idx].person.name : `the “${target.name}” merged in here`;
  const sentence =
    mode === "same"
      ? `${p.name} and ${otherName} are one person.`
      : mode === "different"
        ? `${p.name} is not ${otherName}.`
        : `Hide ${p.name} from the graph and the list.`;

  const button = "inline-flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1 text-[13px] text-ink/90 hover:bg-surface-2 disabled:opacity-50";
  return (
    <Section title="Who is this">
      {mode === null ? (
        <div className="flex flex-wrap gap-1.5">
          <button className={button} disabled={busy} onClick={() => setMode("same")}>
            <Users size={13} /> {EDIT_LABEL.same}
          </button>
          <button className={button} disabled={busy} onClick={() => setMode("different")}>
            <Split size={13} /> {EDIT_LABEL.different}
          </button>
          <button className={button} disabled={busy} onClick={() => setMode("hide")}>
            <EyeOff size={13} /> {EDIT_LABEL.hide}
          </button>
        </div>
      ) : (
        <div className="space-y-2 rounded-xl border border-line p-2.5">
          {mode !== "hide" && target === null && (
            <>
              {mode === "different" && p.aka.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
                  <span>Merged from</span>
                  {p.aka.map((name) => (
                    <button key={name} className={button} onClick={() => setTarget({ name })} title={`${p.name} is not this ${name}`}>
                      {name}
                    </button>
                  ))}
                </div>
              )}
              <label className="relative block">
                <span className="sr-only">Find the other person</span>
                <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted pointer-events-none" />
                <input
                  autoFocus
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => e.key === "Escape" && reset()}
                  placeholder="Find the other person"
                  autoComplete="off"
                  spellCheck={false}
                  className="w-full rounded-lg border border-line-strong bg-surface pl-7 pr-2 py-1.5 text-sm text-ink placeholder:text-muted/80"
                />
              </label>
              {results.length > 0 && (
                <ul className="space-y-0.5">
                  {results.map((i) => {
                    const o = model.nodes[i].person;
                    return (
                      <li key={i}>
                        <button
                          onClick={() => setTarget({ idx: i })}
                          className="w-full text-left rounded-lg px-2 py-1 hover:bg-surface-2"
                        >
                          <span className="block text-sm text-ink truncate">{o.name}</span>
                          {(o.org || o.context) && <span className="block text-xs text-muted truncate">{o.org ?? o.context}</span>}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </>
          )}
          {(mode === "hide" || target !== null) && (
            <p className="text-sm text-ink/90 leading-relaxed break-words">
              {sentence} <span className="text-muted">The index is rebuilt with it; aliases.json keeps it.</span>
            </p>
          )}
          <div className="flex items-center gap-2">
            {(mode === "hide" || target !== null) && (
              <button
                onClick={save}
                disabled={busy}
                className="rounded-lg bg-accent px-3 py-1 text-[13px] font-medium text-accent-ink disabled:opacity-60"
              >
                {busy ? "Saving and rebuilding…" : "Save"}
              </button>
            )}
            <button onClick={reset} disabled={busy} className="text-[13px] text-muted hover:text-ink px-1">
              Cancel
            </button>
          </div>
        </div>
      )}
      {busy && mode === null && <p className="text-xs text-muted">Rebuilding…</p>}
      {note && (
        <p className="text-xs text-muted leading-relaxed">
          {note.text}{" "}
          {note.retry && (
            <button onClick={refresh} disabled={busy} className="text-accent hover:underline underline-offset-4">
              Refresh now
            </button>
          )}
        </p>
      )}
    </Section>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <Label>{title}</Label>
      {children}
    </section>
  );
}

/** One person: who they are, what Proxenos suggests for them, who they're tied to and why. */
export function PersonPanel({
  model,
  idx,
  data,
  flashId,
  groupFocus,
  onSelect,
  onGroup,
  onClose,
  onReact,
  clusters,
  onEdit,
  onRefresh,
}: PersonPanelProps) {
  const [allTies, setAllTies] = useState(false);
  const [allGroups, setAllGroups] = useState(false);
  const node = model.nodes[idx];
  const p = node.person;
  const style = RELATION_STYLE[p.relation];
  const cluster = node.cluster !== null ? clusters.get(node.cluster) : undefined;

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
          {cluster && (
            <div className="mt-1 flex items-center gap-1.5 text-sm text-muted min-w-0" title="The cluster this person is in">
              <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: clusterVar(cluster.id) }} />
              <span className="truncate">{cluster.label}</span>
              <span className="num flex-shrink-0">· {cluster.size}</span>
            </div>
          )}
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
                        {KIND_LABEL_ONE[g.group.kind]} · {plural(g.group.size, "person", "people")}
                        {g.group.size > g.members.length && <> · {g.members.length} drawn</>}
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
                          <span
                            className="num text-xs text-muted flex-shrink-0"
                            title={`${plural(e.shared, "shared context")}, closeness ${e.weight.toFixed(2)}`}
                          >
                            ×{e.shared}
                          </span>
                        </span>
                        {e.contexts.length > 0 && (
                          <span className="line-clamp-2 text-xs text-muted break-words">{e.contexts.join(" · ")}</span>
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

        {onEdit && <WhoIsThis model={model} idx={idx} onEdit={onEdit} onRefresh={onRefresh} />}
      </div>
    </div>
  );
}
