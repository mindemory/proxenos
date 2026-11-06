"use client";

import { useEffect, useState } from "react";
import { ChevronRight, PenLine, ShieldCheck } from "lucide-react";

import { DraftCard } from "@/components/drafts/DraftCard";
import { Outbox } from "@/components/drafts/Outbox";
import { ErrandMessageCard } from "@/components/errands/ErrandMessageCard";
import { TrackRecord } from "@/components/drafts/TrackRecord";
import { EmptyState, ErrorBanner, NoVault } from "@/components/EmptyState";
import { DraftSkeleton } from "@/components/Skeleton";
import { useDrafts } from "@/lib/client";
import {
  ERRAND_STALE_DAYS,
  groupDrafts,
  isNote,
  isStale,
  isStaleErrand,
  needsCheck,
  openErrandItems,
  STALE_DAYS,
  waitingToSend,
} from "@/lib/drafts";
import { useErrands } from "@/lib/errandsClient";
import { scrollBehavior } from "@/lib/reading";
import type { Draft, ThinkStart } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Proxenos acting as you: replies, emails, plans and docs it wrote, for you to copy or open and send.
 * `focus` is a draft opened from another view (the home page). The view takes it on mount and
 * clears it, then shows that draft on its tab, whole, and scrolls to it once the list is there.
 */
export function Drafts({
  onChange,
  focus,
  onFocused,
  onThink,
  onErrand,
}: {
  onChange?: () => void;
  focus?: string | null;
  onFocused?: () => void;
  /** Think a draft through with Proxenos, in a new thread that starts from it. */
  onThink?: (start: ThinkStart) => void;
  /** Open an errand, to read its steps. */
  onErrand?: (id: string) => void;
}) {
  const { data, error, flashId, discard, sent: markSent, keep, done, renew, edit, copy, open, clearError } = useDrafts(onChange);
  const errands = useErrands(onChange);
  const [showSent, setShowSent] = useState<boolean | null>(null);
  const [showNotes, setShowNotes] = useState<boolean | null>(null);
  const [showOlder, setShowOlder] = useState<boolean | null>(null);
  const [showOlderErrands, setShowOlderErrands] = useState(false);
  const [showOvertaken, setShowOvertaken] = useState<boolean | null>(null);
  const [focusId] = useState(focus ?? null);
  const focusDraft = data?.drafts.find((d) => d.id === focusId) ?? null;
  const focusStatus = focusDraft?.status ?? null;

  useEffect(() => {
    if (focus) onFocused?.();
  }, [focus, onFocused]);

  useEffect(() => {
    if (!focusId || !focusStatus) return;
    // After the tab it's on has rendered.
    const timer = window.setTimeout(
      () => document.getElementById(`draft-${focusId}`)?.scrollIntoView({ behavior: scrollBehavior(), block: "start" }),
      60,
    );
    return () => window.clearTimeout(timer);
  }, [focusId, focusStatus]);

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load the drafts: ${error}`} /> : <DraftSkeleton />;
  }
  if (!data.vault.exists) return <NoVault path={data.vault.path} />;

  const kept = data.drafts.filter((d) => d.status !== "discarded");
  // Not sent yet, approved or not: the reader copies or opens one, then says it went. Docs, plans
  // and notes addressed to no one are kept apart, folded away: they don't wait on the reader. Nor
  // does a message left unchanged for STALE_DAYS: it's folded away as older.
  const nowMs = Date.parse(data.now);
  // Overtaken: the messages since showed it isn't needed (someone else did it, or the plan changed).
  const overtaken = kept.filter((d) => d.status === "overtaken");
  const unsent = kept.filter((d) => d.status !== "sent" && d.status !== "overtaken");
  // A message no thread backs, left a week: asked about, not folded away to be forgotten.
  const checking = unsent.filter((d) => needsCheck(d, nowMs));
  const toSend = unsent.filter((d) => !isNote(d) && !isStale(d, nowMs));
  const older = unsent.filter((d) => !isNote(d) && isStale(d, nowMs) && !needsCheck(d, nowMs));
  const notes = unsent.filter((d) => isNote(d));
  const sent = kept.filter((d) => d.status === "sent");
  // One list of what waits to be sent: the drafts, and the messages errands wrote, each thing once.
  const items = openErrandItems(errands.data?.errands ?? []);
  const waiting = waitingToSend(toSend, items);
  const draftsToSend = waiting.flatMap((w) => (w.kind === "draft" ? [w.draft] : []));
  const underOf = new Map(waiting.flatMap((w) => (w.kind === "draft" && w.under ? [[w.draft.id, w.under] as const] : [])));
  const errandCards = waiting.flatMap((w) => (w.kind === "errand" ? [w] : []));
  // An errand is one ask: one nobody touched for ERRAND_STALE_DAYS went some other way, so it folds.
  const fromErrands = errandCards.filter((w) => !isStaleErrand(w.item, nowMs));
  const olderErrands = errandCards.filter((w) => isStaleErrand(w.item, nowMs));
  const busySend = errands.data?.sending?.state === "running" || errands.waiting.some((w) => w.kind === "send");

  const errandCard = ({ item, under }: (typeof errandCards)[number]) => (
    <ErrandMessageCard
      key={`${item.errand.id}-${item.index}`}
      item={item}
      now={data.now}
      busy={busySend}
      under={under}
      onSend={(edits) => void errands.send(item.errand.id, item.index, edits)}
      onMarkSent={() => void errands.markSent(item.errand.id, item.index)}
      onMarkDone={() => void errands.markDone(item.errand.id, item.index)}
      onErrand={onErrand}
    />
  );

  const card = (d: Draft) => (
    <DraftCard
      key={d.id}
      draft={d}
      now={data.now}
      flash={flashId === d.id}
      plan={data.actions[d.id] ?? null}
      onCopy={copy}
      onDiscard={discard}
      onOpen={open}
      onSent={markSent}
      onEdit={edit}
      onKeep={keep}
      under={underOf.get(d.id) ?? null}
      onErrand={onErrand}
      check={needsCheck(d, nowMs) ? { onKeep: renew, onDone: done } : undefined}
      focused={d.id === focusId}
      onThink={
        onThink &&
        ((x) =>
          onThink({
            kind: "draft",
            id: x.id,
            label: `Draft: ${x.title}`,
            text: x.to ? `Help me think this message to ${x.to} through before I send it.` : "Help me think this through before I send it.",
          }))
      }
    />
  );

  if (kept.length === 0 && items.length === 0) {
    return (
      <div className="pb-24 md:pb-20">
        {error && <ErrorBanner message={error} onDismiss={clearError} />}
        {data.record.reviewed > 0 && <TrackRecord record={data.record} closeness={data.closeness} />}
        <Outbox />
        <EmptyState icon={PenLine} title="No drafts yet" command="proxenos clone work">
          Drafts appear when Proxenos works through your tasks, outreach, projects and reading: replies, emails, plans
          and notes written as you, ready to copy or open and send. Nothing is sent for you unless you switch on the Outbox.
        </EmptyState>
      </div>
    );
  }

  const sentOpen = showSent ?? focusStatus === "sent";
  const notesOpen = showNotes ?? notes.some((d) => d.id === focusId);
  const olderOpen = showOlder ?? older.some((d) => d.id === focusId);
  const overtakenOpen = showOvertaken ?? overtaken.some((d) => d.id === focusId);
  const grouped = (list: Draft[]) => (
    <div className="mt-3 space-y-8">
      {groupDrafts(list).map((g) => (
        <section key={g.id} aria-label={g.label}>
          <h3 className="mb-3 flex items-baseline gap-2 text-lg text-ink">
            {g.label}
            <span className="num text-sm text-muted">{g.drafts.length}</span>
          </h3>
          <div className="grid gap-4 grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 items-start">{g.drafts.map(card)}</div>
        </section>
      ))}
    </div>
  );
  const groups = groupDrafts(draftsToSend);

  return (
    <div className="pb-24 md:pb-20">
      {error && <ErrorBanner message={error} onDismiss={clearError} />}

      <TrackRecord record={data.record} closeness={data.closeness} />
      <Outbox />

      <div className="px-4 sm:px-6 py-3 border-b border-line flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="text-sm text-ink">
          To send <span className="num text-muted">{waiting.length}</span>
        </p>
        <p className="flex items-center gap-1.5 text-sm text-muted sm:ml-auto">
          <ShieldCheck size={15} className="text-ok-ink flex-shrink-0" />
          Drafts and what your errands wrote, each once. Copy one, or open it in its app with the text filled in. You press send, then mark it sent here, or
          Done when it isn&apos;t needed.
        </p>
      </div>

      {errands.error && <ErrorBanner message={errands.error} onDismiss={errands.clearError} />}

      {waiting.length === 0 ? (
        <p className="px-4 sm:px-6 py-8 text-sm text-muted">
          Nothing left to send.
        </p>
      ) : (
        <div className="p-4 sm:p-6 space-y-8">
          {fromErrands.length > 0 && (
            <section aria-labelledby="drafts-errands">
              <h2 id="drafts-errands" className="font-display text-2xl text-ink mb-3 flex items-baseline gap-2">
                From errands
                <span className="num text-sm text-muted">{fromErrands.length}</span>
              </h2>
              <div className="grid gap-4 grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 items-start">
                {fromErrands.map(errandCard)}
              </div>
            </section>
          )}
          {groups.map((g) => (
            <section key={g.id} aria-labelledby={`drafts-${g.id}`}>
              <h2 id={`drafts-${g.id}`} className="font-display text-2xl text-ink mb-3 flex items-baseline gap-2">
                {g.label}
                <span className="num text-sm text-muted">{g.drafts.length}</span>
              </h2>
              <div className="grid gap-4 grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 items-start">{g.drafts.map(card)}</div>
            </section>
          ))}
        </div>
      )}

      {checking.length > 0 && (
        <section aria-labelledby="drafts-check" className="px-4 sm:px-6 pb-6">
          <h2 id="drafts-check" className="font-display text-2xl text-ink flex items-baseline gap-2">
            Is this still needed?
            <span className="num text-sm text-muted">{checking.length}</span>
          </h2>
          <p className="mt-1 text-sm text-muted">
            No conversation shows whether these went out, and they&apos;re a week old. Keep what you still mean to send; mark the rest done.
          </p>
          <div className="mt-3 grid gap-4 grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 items-start">{checking.map(card)}</div>
        </section>
      )}

      {olderErrands.length > 0 && (
        <Folded
          id="drafts-older-errands"
          title="Older errands"
          count={olderErrands.length}
          hint={`Errands not touched for ${ERRAND_STALE_DAYS} day or more, so likely handled some other way. Done clears one; Mark sent if it went out.`}
          open={showOlderErrands}
          onToggle={() => setShowOlderErrands(!showOlderErrands)}
        >
          <div className="grid gap-4 grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 items-start">{olderErrands.map(errandCard)}</div>
        </Folded>
      )}

      {older.length > 0 && (
        <Folded
          id="drafts-older"
          title="Older"
          count={older.length}
          hint={`Not changed for ${STALE_DAYS} days or more, so likely handled some other way. Discard what you don't need.`}
          open={olderOpen}
          onToggle={() => setShowOlder(!olderOpen)}
        >
          {grouped(older)}
        </Folded>
      )}

      {overtaken.length > 0 && (
        <Folded
          id="drafts-overtaken"
          title="Overtaken"
          count={overtaken.length}
          hint="Your messages since show these aren't needed: someone else did it, you said it another way, or the plan changed. Each says why."
          open={overtakenOpen}
          onToggle={() => setShowOvertaken(!overtakenOpen)}
        >
          {grouped(overtaken)}
        </Folded>
      )}

      {notes.length > 0 && (
        <Folded
          id="drafts-notes"
          title="Notes and plans"
          count={notes.length}
          hint="Reading notes, project plans and checklists for you to keep. Nothing to send."
          open={notesOpen}
          onToggle={() => setShowNotes(!notesOpen)}
        >
          {grouped(notes)}
        </Folded>
      )}

      {sent.length > 0 && (
        <section aria-labelledby="drafts-sent" className="px-4 sm:px-6 pb-6">
          <h2 id="drafts-sent" className="font-display text-2xl text-ink">
            <button
              onClick={() => setShowSent(!sentOpen)}
              aria-expanded={sentOpen}
              className="flex items-baseline gap-2 text-left hover:text-accent transition-colors"
            >
              <ChevronRight size={18} className={cn("self-center transition-transform", sentOpen && "rotate-90")} />
              Sent
              <span className="num text-sm text-muted">{sent.length}</span>
            </button>
          </h2>
          {sentOpen && (
            <div className="mt-3 grid gap-4 grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 items-start">
              {[...sent].sort((a, b) => Date.parse(b.created ?? "") - Date.parse(a.created ?? "") || 0).map(card)}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

/** A section folded away under its heading, with a line saying what's in it while it's closed. */
function Folded({
  id,
  title,
  count,
  hint,
  open,
  onToggle,
  children,
}: {
  id: string;
  title: string;
  count: number;
  hint: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="px-4 sm:px-6 pb-6">
      <h2 id={id} className="font-display text-2xl text-ink">
        <button onClick={onToggle} aria-expanded={open} className="flex items-baseline gap-2 text-left hover:text-accent transition-colors">
          <ChevronRight size={18} className={cn("self-center transition-transform", open && "rotate-90")} />
          {title}
          <span className="num text-sm text-muted">{count}</span>
        </button>
      </h2>
      {open ? children : <p className="mt-1 text-sm text-muted">{hint}</p>}
    </section>
  );
}
