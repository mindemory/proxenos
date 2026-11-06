"use client";

import { useState } from "react";
import { Compass } from "lucide-react";

import { ChoiceCard } from "@/components/choices/ChoiceCard";
import { Command, EmptyState, ErrorBanner, NoVault } from "@/components/EmptyState";
import { ProseSkeleton } from "@/components/Skeleton";
import { useToast } from "@/components/Toasts";
import { useChoices } from "@/lib/client";
import { errandFromGoal } from "@/lib/errandsClient";
import { formatDateTime, shortDate, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

interface ChoicesProps {
  onChange?: () => void;
  /** Open a choice's draft in Drafts. */
  onDraft?: (id: string) => void;
  /** Go to Errands once a choice's errand has started. */
  onErrands?: () => void;
  /** Open one piece of evidence in Memory. */
  onMemory?: (query: string, id?: string) => void;
}

/**
 * The week's choices: openings worth taking on, each with why it fits and a first step ready to
 * go, and what's worth letting go of, each with what it costs and, when someone is owed an
 * answer, a decline drafted. Each takes useful, not me or doing, which the next week learns from.
 */
export function Choices({ onChange, onDraft, onErrands, onMemory }: ChoicesProps) {
  const [date, setDate] = useState<string | null>(null);
  const { data, error, flashId, react, clearError } = useChoices(date, onChange);
  const notify = useToast();
  const [errandError, setErrandError] = useState<string | null>(null);

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load choices: ${error}`} /> : <ProseSkeleton label="Loading choices" />;
  }

  if (!data.vault.exists) return <NoVault path={data.vault.path} />;

  if (!data.date) {
    return (
      <EmptyState icon={Compass} title="No choices yet" command="proxenos clone choices --force">
        Once a week, Proxenos reads the calls, fellowships, talks and events that reached you, and what your meetings, threads and lists
        cost you. It picks what is worth taking on and what is worth letting go, by your own goals. The night job runs it. Press Make it
        now to run it right away.
      </EmptyState>
    );
  }

  const startErrand = (goal: string) => {
    setErrandError(null);
    errandFromGoal(goal).then(
      () => {
        notify("Errand started", "ok");
        onErrands?.();
      },
      (e: unknown) => setErrandError(e instanceof Error ? e.message : String(e)),
    );
  };

  const switching = date !== null && data.date !== date;
  const all = [...data.take_on, ...data.skip];
  const unanswered = all.filter((c) => c.action === null).length;
  const card = { now: data.now, onReact: react, onDraft, onErrand: startErrand, onMemory };

  return (
    <div className="pb-24 md:pb-20">
      {(error || errandError) && (
        <ErrorBanner
          message={errandError ?? error ?? ""}
          onDismiss={() => {
            setErrandError(null);
            clearError();
          }}
        />
      )}

      <div className="px-4 sm:px-6 py-3 border-b border-line flex flex-wrap items-center justify-between gap-x-4 gap-y-2 text-sm text-muted">
        <label className="inline-flex items-center gap-2">
          <span>Week of</span>
          <select
            value={data.date}
            onChange={(e) => setDate(e.target.value)}
            className="num bg-surface border border-line-strong rounded-full px-3 py-1 text-sm text-ink hover:border-accent/40"
          >
            {data.dates.map((d, i) => (
              <option key={d} value={d}>
                {shortDate(d, data.now)}
                {i === 0 ? " (latest)" : ""}
              </option>
            ))}
          </select>
        </label>
        <span>
          {data.generated && (
            <span title={formatDateTime(data.generated)}>
              Chosen <span className="num">{timeAgo(data.generated, data.now)}</span> ·{" "}
            </span>
          )}
          <span className="num">{unanswered}</span> of <span className="num">{all.length}</span> not answered
        </span>
      </div>

      <div className={cn("p-4 sm:p-6 space-y-8 transition-opacity", switching && "opacity-50")} aria-busy={switching}>
        <section aria-label="Worth taking on" className="space-y-4">
          <div>
            <p className="smallcaps text-accent">Worth taking on</p>
            <p className="mt-1 text-sm text-muted">Openings that fit who you are and where you&apos;re headed, with a first step ready.</p>
          </div>
          {data.take_on.length > 0 ? (
            data.take_on.map((c) => <ChoiceCard key={c.id} side="take_on" c={c} flash={flashId === c.id} {...card} />)
          ) : (
            <p className="text-sm text-muted">Nothing cleared the bar this week.</p>
          )}
        </section>

        <section aria-label="Worth skipping" className="space-y-4">
          <div>
            <p className="smallcaps">Worth skipping</p>
            <p className="mt-1 text-sm text-muted">What costs you more than it gives: meetings, threads, invitations, lists and channels.</p>
          </div>
          {data.skip.length > 0 ? (
            data.skip.map((c) => <ChoiceCard key={c.id} side="skip" c={c} flash={flashId === c.id} {...card} />)
          ) : (
            <p className="text-sm text-muted">Nothing to let go of this week.</p>
          )}
        </section>

        <p className="text-xs text-muted">
          Each answer is appended to <code className="num">clones/choices/feedback.jsonl</code> in the vault; what you mark not me never
          comes back. <Command>proxenos clone choices --force</Command> chooses again now.
        </p>
      </div>
    </div>
  );
}
