"use client";

import { useState } from "react";
import { FileText, GitMerge, Trash2, TriangleAlert, X } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { Fold } from "@/components/ask/parts";
import { Markdown } from "@/components/Markdown";
import { formatDateTime, timeAgo } from "@/lib/format";
import type { ProjectStep, StepStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS: Record<StepStatus, { label: string; tone: string }> = {
  working: { label: "Working on it", tone: "border-accent/40 bg-accent/10 text-accent" },
  ready: { label: "Waiting on you", tone: "border-warn-line bg-warn-bg text-warn-ink" },
  failed: { label: "Didn't finish", tone: "border-bad-line bg-bad-bg text-bad-ink" },
  accepted: { label: "Accepted", tone: "border-ok-line bg-ok-bg text-ok-ink" },
  discarded: { label: "Discarded", tone: "border-line-strong bg-surface-2 text-muted" },
};

const RUNNER = { claude: "Claude Code", local: "the local model", "": "" } as const;

function madeUrl(step: string, name: string): string {
  return `/api/projects/file?step=${encodeURIComponent(step)}&name=${encodeURIComponent(name)}`;
}

function Part({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-1.5">
      <p className="smallcaps">{title}</p>
      {children}
    </section>
  );
}

interface StepCardProps {
  step: ProjectStep;
  now: string;
  /** An Accept or Discard is going. */
  busy: boolean;
  onAccept: () => void;
  onDiscard: () => void;
}

/** One step of a project's work: what it did, what it shows, what it changed, and Accept or Discard. */
export function StepCard({ step, now, busy, onAccept, onDiscard }: StepCardProps) {
  const [confirm, setConfirm] = useState<"accept" | "discard" | null>(null);
  const status = STATUS[step.status];
  const decided = step.status === "accepted" || step.status === "discarded";
  const runner = RUNNER[step.runner];
  const added = step.files.reduce((n, f) => n + f.added, 0);
  const removed = step.files.reduce((n, f) => n + f.removed, 0);
  const figures = step.made.filter((m) => m.image);
  const tables = step.made.filter((m) => !m.image);

  const report = (
    <>
      {step.did && (
        <Part title="What it did">
          <Markdown source={step.did} compact />
        </Part>
      )}
      {(step.found || figures.length > 0) && (
        <Part title="What it shows">
          {step.found && <Markdown source={step.found} compact />}
          {figures.length > 0 && (
            <div className="grid gap-3 pt-1 sm:grid-cols-2">
              {figures.map((f) => (
                <figure key={f.name} className="space-y-1">
                  <a href={madeUrl(step.id, f.name)} target="_blank" rel="noreferrer" className="block">
                    {/* A figure the step made, from the vault: a plain img, no optimizing server in between. */}
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={madeUrl(step.id, f.name)}
                      alt={f.caption || f.name}
                      loading="lazy"
                      className="w-full rounded-lg border border-line bg-white"
                    />
                  </a>
                  <figcaption className="text-xs text-muted">{f.caption || f.name}</figcaption>
                </figure>
              ))}
            </div>
          )}
        </Part>
      )}
      {tables.length > 0 && (
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {tables.map((t) => (
            <li key={t.name}>
              <a
                href={madeUrl(step.id, t.name)}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 text-accent hover:underline"
              >
                <FileText size={13} aria-hidden="true" />
                {t.name}
              </a>
              {t.caption && <span className="text-muted"> · {t.caption}</span>}
            </li>
          ))}
        </ul>
      )}
      {step.files.length > 0 && (
        <Part title={`Files changed (${step.files.length})`}>
          <ul className="space-y-0.5 font-mono text-xs">
            {step.files.map((f) => (
              <li key={f.path} className="flex min-w-0 gap-3">
                <span className="min-w-0 truncate text-ink/90">{f.path}</span>
                <span className="num flex-shrink-0 text-ok-ink">+{f.added}</span>
                <span className="num flex-shrink-0 text-bad-ink">−{f.removed}</span>
              </li>
            ))}
          </ul>
          {step.branch && (
            <p className="text-xs text-muted">
              On <span className="font-mono text-ink/90">{step.branch}</span>
              {step.base && (
                <>
                  , from <span className="font-mono text-ink/90">{step.base}</span>
                </>
              )}
              {step.worktree && (
                <>
                  , checked out in <span className="font-mono text-ink/90">{step.worktree}</span>
                </>
              )}
              .
            </p>
          )}
        </Part>
      )}
      {step.couldnt && (
        <Part title="What it couldn't do">
          <Markdown source={step.couldnt} compact />
        </Part>
      )}
      {step.next && (
        <Part title="Next">
          <p className="text-sm leading-relaxed text-ink/90">{step.next}</p>
        </Part>
      )}
    </>
  );

  return (
    <article id={`step-${step.id}`} className="card flex min-w-0 scroll-mt-20 flex-col gap-4 p-4 sm:p-5">
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
          <span className={cn("inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs", status.tone)}>{status.label}</span>
          {step.created && (
            <span className="text-xs text-muted" title={formatDateTime(step.created)}>
              <span className="num">{timeAgo(step.created, now)}</span>
              {runner && ` · by ${runner}`}
              {step.turns !== null && step.turns > 0 && ` · ${step.turns} turns`}
            </span>
          )}
        </div>
        <h3 className="text-base font-medium leading-snug text-ink">{step.step || step.asked || "A step of the project's work"}</h3>
        {step.asked && step.step && step.asked !== step.step && <p className="text-xs text-muted">You asked: {step.asked}</p>}
        {step.why && <p className="text-sm leading-relaxed text-muted">{step.why}</p>}
      </div>

      {step.status === "failed" && (
        <div className="flex items-start gap-2.5 rounded-xl border border-bad-line bg-bad-bg p-3 text-sm text-bad-ink">
          <TriangleAlert size={16} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
          <span className="min-w-0 break-words">{step.error ?? "It didn't finish."}</span>
        </div>
      )}

      {decided ? (
        <Fold label={`The report${step.files.length ? ` · ${step.files.length} files, +${added} −${removed}` : ""}`}>
          <div className="space-y-4">{report}</div>
        </Fold>
      ) : (
        report
      )}

      {step.thread.length > 0 && (
        <Fold label={`Every part of the run (${step.thread.length})`}>
          <ol className="space-y-2.5">
            {step.thread.map((s, i) => (
              <li key={`${i}-${s.at}`} className="text-sm leading-relaxed">
                <span className="font-medium text-ink">{s.title}</span>
                {s.at && (
                  <span className="ml-2 text-xs text-faint" title={formatDateTime(s.at)}>
                    {timeAgo(s.at, now)}
                  </span>
                )}
                <p className="whitespace-pre-wrap break-words text-muted">{s.detail}</p>
              </li>
            ))}
          </ol>
        </Fold>
      )}

      {(step.status === "ready" || (step.status === "failed" && step.worktree)) && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            {confirm === "accept" ? (
              <>
                <ActionButton
                  icon={GitMerge}
                  label={`Merge into ${step.base || "your branch"}`}
                  tone="ok"
                  active
                  fillWhenActive
                  disabled={busy}
                  onClick={() => {
                    setConfirm(null);
                    onAccept();
                  }}
                />
                <ActionButton icon={X} label="Not yet" tone="neutral" onClick={() => setConfirm(null)} />
              </>
            ) : confirm === "discard" ? (
              <>
                <ActionButton
                  icon={Trash2}
                  label="Delete the branch"
                  tone="bad"
                  active
                  disabled={busy}
                  onClick={() => {
                    setConfirm(null);
                    onDiscard();
                  }}
                />
                <ActionButton icon={X} label="Keep it" tone="neutral" onClick={() => setConfirm(null)} />
              </>
            ) : (
              <>
                {step.status === "ready" && (
                  <ActionButton icon={GitMerge} label="Accept" tone="ok" disabled={busy} onClick={() => setConfirm("accept")} />
                )}
                <ActionButton icon={Trash2} label="Discard" tone="bad" disabled={busy} onClick={() => setConfirm("discard")} />
              </>
            )}
          </div>
          <p className="text-xs text-muted">
            {confirm === "accept"
              ? `This merges ${step.branch} into ${step.base} in your own checkout. Nothing is pushed.`
              : confirm === "discard"
                ? `This deletes ${step.branch} and its worktree. The report stays here.`
                : step.status === "ready"
                  ? step.files.length
                    ? `Accept merges it into ${step.base} in your checkout; Discard deletes the branch.`
                    : "It changed no file: Accept marks it done; Discard sets it aside."
                  : "Its worktree is kept as it stopped, for you to look at. Discard deletes it and the branch."}
          </p>
          {busy && <p className="text-xs text-muted">The last decision is still going.</p>}
        </div>
      )}
    </article>
  );
}
