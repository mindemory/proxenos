"use client";

import { useEffect, useState } from "react";
import { ChevronRight, HeartPulse, Info } from "lucide-react";

import { CareItemRow, ScriptCard, SectionHeader, Timeline, VisitBrief, type OpenRecord } from "@/components/care/parts";
import { EmptyState, ErrorBanner, NoVault } from "@/components/EmptyState";
import { Segmented } from "@/components/layout/Segmented";
import { ProseSkeleton } from "@/components/Skeleton";
import { CARE_GROUPS, careStatus, groupCare, useCare } from "@/lib/careClient";
import { formatDateTime, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

type CareTab = "overview" | "brief";

const TABS: { id: CareTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "brief", label: "Visit brief" },
];

interface CareProps {
  onChange?: () => void;
  /** Open one piece of evidence in Memory. */
  onMemory?: OpenRecord;
  /** An item opened from the home page: taken on mount and cleared, then scrolled to once the list is there. */
  focus?: string | null;
  onFocused?: () => void;
}

export function Care({ onChange, onMemory, focus, onFocused }: CareProps) {
  const { data, error, flashId, act, clearError } = useCare(onChange);
  const [tab, setTab] = useState<CareTab>("overview");
  const [focusId] = useState(focus ?? null);
  const focusItem = data?.items.find((i) => i.id === focusId) ?? null;
  const [showDone, setShowDone] = useState<boolean | null>(null);
  const doneOpen = showDone ?? (focusItem !== null && careStatus(focusItem) === "done");

  useEffect(() => {
    if (focus) onFocused?.();
  }, [focus, onFocused]);

  const found = focusItem !== null;
  useEffect(() => {
    if (!focusId || !found) return;
    // After its group has rendered.
    const timer = window.setTimeout(
      () => document.getElementById(`care-${focusId}`)?.scrollIntoView({ behavior: "smooth", block: "start" }),
      60,
    );
    return () => window.clearTimeout(timer);
  }, [focusId, found]);

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load care: ${error}`} /> : <ProseSkeleton label="Loading care" />;
  }
  if (!data.vault.exists) return <NoVault path={data.vault.path} />;
  if (!data.exists) {
    return (
      <EmptyState icon={HeartPulse} title="Nothing on your care yet" command="proxenos clone care">
        The care clone picks the health-care admin out of your mail, calendar, chats and notes (visits, tests,
        referrals, bills, insurance, records) and lays out where things stand, what&apos;s still open, and what to say
        on the phone. Only those records go to the model, with names and numbers blanked.
      </EmptyState>
    );
  }

  const { groups, done } = groupCare(data.items);
  const openCount = Object.values(groups).reduce((n, list) => n + list.length, 0);
  const titles = new Map(data.items.map((i) => [i.id, i.title]));
  const liveScripts = data.scripts.filter((s) => {
    const item = data.items.find((i) => i.id === s.item_id);
    const place = item ? careStatus(item) : null;
    return place === "open" || place === "waiting";
  });
  const scriptsFor = (id: string) => liveScripts.filter((s) => s.item_id === id).length;
  const read = Object.values(data.records).reduce((n, v) => n + v, 0);
  const empty = !data.summary && data.timeline.length === 0 && data.items.length === 0;

  return (
    <div className="pb-24 md:pb-20">
      {error && <ErrorBanner message={error} onDismiss={clearError} />}

      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-line px-4 py-3 sm:px-6">
        <Segmented label="Care" tabs={TABS} value={tab} onChange={setTab} />
        {data.generated && (
          <span className="text-sm text-muted" title={formatDateTime(data.generated)}>
            Updated <span className="num">{timeAgo(data.generated, data.now)}</span>
            {read > 0 && (
              <>
                {" "}
                · from <span className="num">{read}</span> {read === 1 ? "record" : "records"}
              </>
            )}
          </span>
        )}
      </div>

      {tab === "brief" ? (
        data.visit_brief ? (
          <VisitBrief brief={data.visit_brief} generated={data.generated} />
        ) : (
          <p className="px-4 py-6 text-sm text-muted sm:px-6">No visit brief yet. The next run of the care clone writes one.</p>
        )
      ) : empty ? (
        <p className="px-4 py-6 text-sm leading-relaxed text-muted sm:px-6">
          Nothing about health care turned up in your records for the window the care clone reads.
        </p>
      ) : (
        <>
          {data.summary && (
            <section aria-labelledby="care-status" className="border-b border-line px-4 py-5 sm:px-6">
              <h2 id="care-status" className="smallcaps mb-2">
                Where things stand
              </h2>
              <p className="text-[1.0625rem] leading-relaxed text-ink">{data.summary}</p>
              <p className="mt-3 flex items-start gap-1.5 text-xs leading-relaxed text-muted">
                <Info size={13} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
                Restated from your own mail, calendar, chats and notes. Proxenos doesn&apos;t diagnose: check anything
                that matters with your care team.
              </p>
            </section>
          )}

          <section aria-label="Open items">
            {openCount === 0 && (
              <>
                <SectionHeader title="Open items" count={0} />
                <p className="border-b border-line px-4 py-4 text-sm text-muted sm:px-6">Nothing open.</p>
              </>
            )}
            {CARE_GROUPS.filter((g) => groups[g.id].length > 0).map((g) => (
              <div key={g.id}>
                <SectionHeader title={g.label} hint={g.hint} count={groups[g.id].length} />
                <ul className="divide-y divide-line border-b border-line">
                  {groups[g.id].map((i) => (
                    <CareItemRow
                      key={i.id}
                      item={i}
                      now={data.now}
                      cited={data.cited}
                      scripts={scriptsFor(i.id)}
                      flash={flashId === i.id}
                      focused={i.id === focusId}
                      onAct={act}
                      onOpen={onMemory}
                    />
                  ))}
                </ul>
              </div>
            ))}
            {done.length > 0 && (
              <div>
                <button
                  onClick={() => setShowDone(!doneOpen)}
                  aria-expanded={doneOpen}
                  className={cn(
                    "flex w-full justify-between gap-3 border-b border-line bg-surface/60 px-4 py-2 text-left hover:bg-surface sm:px-6",
                    flashId === "group:done" && "row-flash",
                  )}
                >
                  <span className="eyebrow inline-flex items-center gap-1">
                    <ChevronRight size={12} className={cn("transition-transform", doneOpen && "rotate-90")} />
                    Done
                  </span>
                  <span className="num text-xs text-muted">{done.length}</span>
                </button>
                {doneOpen && (
                  <ul className="divide-y divide-line border-b border-line">
                    {done.map((i) => (
                      <CareItemRow key={i.id} item={i} now={data.now} cited={data.cited} focused={i.id === focusId} onOpen={onMemory} />
                    ))}
                  </ul>
                )}
              </div>
            )}
          </section>

          {data.timeline.length > 0 && (
            <section aria-label="Timeline" className="border-b border-line">
              <SectionHeader title="Timeline" hint="oldest first" count={data.timeline.length} />
              <Timeline events={data.timeline} now={data.now} cited={data.cited} onOpen={onMemory} />
            </section>
          )}

          {liveScripts.length > 0 && (
            <section aria-label="Scripts">
              <SectionHeader title="What to say" hint="copy, then call, write or fill in yourself" count={liveScripts.length} />
              <ul className="space-y-3 px-4 py-4 sm:px-6">
                {liveScripts.map((s) => (
                  <ScriptCard key={s.id} script={s} itemTitle={titles.get(s.item_id)} />
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}
