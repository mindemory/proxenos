"use client";

import { useState } from "react";
import { ClipboardCheck } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { Fold } from "@/components/ask/parts";
import { ErrorBanner } from "@/components/EmptyState";
import { Markdown } from "@/components/Markdown";
import { timeAgo } from "@/lib/format";
import { useReviews } from "@/lib/projectsClient";
import {
  REVIEW_ROUNDS_DEFAULT,
  REVIEW_ROUNDS_MAX,
  type ConcernStatus,
  type ReviewConcern,
  type ReviewRound,
  type ReviewRun,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<ConcernStatus, string> = {
  open: "text-warn-ink",
  "not resolved": "text-bad-ink",
  "partly resolved": "text-warn-ink",
  resolved: "text-ok-ink",
};

const RUN_WORDS: Record<ReviewRun["status"], string> = {
  working: "Going",
  done: "Done",
  stopped: "Stopped",
  failed: "Failed",
};

/** A model's name as the page says it: Claude Code, or the name itself. */
function modelName(model: string): string {
  if (model === "claude-code") return "Claude Code";
  if (model.startsWith("claude-")) return `Claude (${model})`;
  return model.replace(/^(ollama|local):/, "") + " on this computer";
}

/** Every concern of a review, by reviewer, with what each round made of it. */
function Concerns({ concerns }: { concerns: ReviewConcern[] }) {
  if (!concerns.length) return null;
  const open = concerns.filter((c) => c.status !== "resolved").length;
  return (
    <Fold label={`Every concern: ${concerns.length}, ${open} still open`}>
      <ul className="space-y-1.5 text-sm">
        {concerns.map((c) => (
          <li key={c.id}>
            <p className="break-words text-ink/90">
              <span className="num font-mono text-xs text-muted">{c.id}</span> {c.title}
              {c.kind === "major" && <span className="text-xs text-muted"> · major</span>}
            </p>
            <p className={cn("text-xs", STATUS_TONE[c.status])}>
              {c.history.map((h) => `${h.status} in round ${h.round}`).join(", then ")}
            </p>
          </li>
        ))}
      </ul>
    </Fold>
  );
}

/** One round: each reviewer's report, the plan, the steps of its revision and the letter. */
function Round({ round, run, last }: { round: ReviewRound; run: ReviewRun; last: boolean }) {
  const lens = new Map(run.reviewers.map((r) => [r.n, r.lens]));
  const verdicts = round.reviews
    .map((r) => `${r.recommendation || "no recommendation"}${r.score !== null ? `, ${r.score}/10` : ""}`)
    .join("; ");
  return (
    <section aria-label={`Round ${round.n}`} className="space-y-2">
      <h4 className="text-sm font-medium text-ink">
        Round {round.n}
        <span className="font-normal text-muted">
          {" "}
          · {round.openMajor} major and {round.openMinor} minor concerns to answer
          {round.status !== "done" && ` · ${round.status}`}
        </span>
      </h4>
      {verdicts && <p className="text-xs text-muted">{verdicts}</p>}
      {round.error && <p className="text-sm text-bad-ink">{round.error}</p>}
      {round.reviews.map((r) => (
        <Fold key={r.n} label={`Reviewer ${r.n}${lens.get(r.n) ? `, ${lens.get(r.n)}` : ""}`}>
          {r.text ? <Markdown source={r.text} compact /> : <p className="text-sm text-muted">Not kept.</p>}
        </Fold>
      ))}
      {round.planText && (
        <Fold label={`The plan: ${round.plan.text} to the text, ${round.plan.analysis} to the analysis, ${round.plan.later} later, ${round.plan.decline} declined`}>
          <Markdown source={round.planText} compact />
        </Fold>
      )}
      {round.steps.length > 0 && (
        <p className="text-xs text-muted">
          Its revision is {round.steps.length === 1 ? "a step" : `${round.steps.length} steps`} on{" "}
          {round.steps.length === 1 ? "a branch" : "branches"} of its own, with your project&apos;s other steps below: Accept merges,
          Discard deletes.
        </p>
      )}
      {round.response && (
        <Fold label="The response letter" start={last}>
          <Markdown source={round.response} compact />
        </Fold>
      )}
    </section>
  );
}

/** A review: who reviewed, what's still open, and each round. */
function Run({ run, now, newest }: { run: ReviewRun; now: string; newest: boolean }) {
  const body = (
    <div className="space-y-4">
      <p className="text-sm text-ink/90">{run.summary || run.error}</p>
      <p className="text-xs text-muted">
        {run.manuscript.path} on {run.manuscript.branch} · {modelName(run.model)} · started {timeAgo(run.created, now)}
        {run.field && ` · ${run.field}`}
        {run.venue && `, for ${run.venue}`}
      </p>
      {run.reviewers.length > 0 && (
        <ul className="space-y-0.5 text-xs text-muted">
          {run.reviewers.map((r) => (
            <li key={r.n}>
              <span className="text-ink/90">Reviewer {r.n}, {r.lens}.</span> {r.expertise}
            </li>
          ))}
        </ul>
      )}
      <Concerns concerns={run.concerns} />
      {run.rounds.map((round, i) => (
        <Round key={round.n} round={round} run={run} last={newest && i === run.rounds.length - 1} />
      ))}
    </div>
  );
  if (newest) return body;
  return <Fold label={`${RUN_WORDS[run.status]}, ${timeAgo(run.created, now)}: ${run.summary || run.error}`}>{body}</Fold>;
}

/**
 * A paper's peer review: two or three reviewers, each with a lens of their own, read the
 * manuscript and its code and report; the author's plan sorts what they ask; the revision comes
 * back as steps; a letter answers them; and the same reviewers read the revision, up to the
 * rounds asked for. Nothing starts until the user presses Review it.
 */
export function ReviewPanel({ project, onSteps }: { project: string; onSteps: () => void }) {
  const { data, error, going, start, actionError, clearActionError } = useReviews(project, onSteps);
  const [rounds, setRounds] = useState(REVIEW_ROUNDS_DEFAULT);
  const runs = data?.runs ?? [];
  const working = runs[0]?.status === "working" ? runs[0] : null;
  return (
    <section aria-label="Peer review" className="card space-y-4 p-4 sm:p-5">
      <div className="space-y-1">
        <p className="smallcaps text-accent">Peer review</p>
        <p className="text-sm leading-relaxed text-muted">
          Reviewers with different lenses (its field, its methods and statistics, its venue&apos;s readers) read the paper and its code
          and report; a plan sorts what they ask; the revision comes back as steps for you to accept; a letter answers them, in your
          voice; then they read the revision. It stops once no major concern is left. The paper, its code and its brief go to the review
          model, Claude unless you chose another in Settings, only when you press Review it. Your messages never do.
        </p>
      </div>
      {actionError && <ErrorBanner message={actionError} onDismiss={clearActionError} />}
      {error && !data && <ErrorBanner message={`Couldn't read its reviews: ${error}`} />}
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-xs text-muted">
          Up to
          <select
            value={rounds}
            onChange={(e) => setRounds(Number(e.target.value))}
            disabled={going}
            className="rounded-lg border border-line-strong bg-surface px-2 py-1 text-sm text-ink hover:border-accent/40"
          >
            {Array.from({ length: REVIEW_ROUNDS_MAX }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>
                {n} {n === 1 ? "round" : "rounds"}
              </option>
            ))}
          </select>
        </label>
        <ActionButton
          icon={ClipboardCheck}
          label={going ? "Reviewing…" : "Review it"}
          tone="accent"
          disabled={going}
          onClick={() => start(rounds)}
        />
        {working?.latest && (
          <span aria-live="polite" className="text-xs text-muted">
            {working.latest.title}
            {working.latest.detail && `: ${working.latest.detail}`} · {timeAgo(working.latest.at, data?.now ?? "")}
          </span>
        )}
      </div>
      {data?.job?.state === "failed" && !working && runs[0]?.status !== "failed" && (
        <p className="text-sm text-bad-ink">{data.job.message || "The review stopped before it finished."}</p>
      )}
      {runs.length > 0 && data && <Run run={runs[0]} now={data.now} newest />}
      {runs.length > 1 && data && (
        <div className="space-y-2">
          <p className="text-xs text-muted">Earlier reviews</p>
          {runs.slice(1).map((run) => (
            <Run key={run.id} run={run} now={data.now} newest={false} />
          ))}
        </div>
      )}
    </section>
  );
}
