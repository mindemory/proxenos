"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { ErrorBanner, NoVault } from "@/components/EmptyState";
import { ErrandCard } from "@/components/errands/ErrandCard";
import { Bone } from "@/components/Skeleton";
import { useErrands } from "@/lib/errandsClient";
import { timeAgo } from "@/lib/format";
import { ERRAND_MAX_GOAL } from "@/lib/types";

// What was being written when the view was left, so coming back to it doesn't lose it.
let kept = "";

/**
 * Hand the twin something to get done: it carries it as far as it can without you, and stops one
 * tap short, with an account of every step. Nothing goes out until you press Send on it.
 */
export function Errands() {
  const { data, error, clearError, waiting, start, send, drop } = useErrands();
  const [goal, setGoal] = useState(kept);
  const [starting, setStarting] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    kept = goal;
  }, [goal]);

  if (data && !data.vault.exists) return <NoVault path={data.vault.path} />;

  const working = data?.errands.find((e) => e.status === "working") ?? null;
  const busyErrand = data?.job?.state === "running" || waiting.some((w) => w.kind === "errand");
  const busySend = data?.sending?.state === "running" || waiting.some((w) => w.kind === "send");
  const canStart = goal.trim() !== "" && goal.length <= ERRAND_MAX_GOAL && !starting && !busyErrand;

  const submit = async () => {
    if (!canStart) return;
    setStarting(true);
    const ok = await start(goal.trim());
    setStarting(false);
    if (ok) setGoal("");
  };

  return (
    <div className="space-y-6 p-4 pb-24 sm:p-6 md:pb-20">
      {error && <ErrorBanner message={error} onDismiss={data ? clearError : undefined} />}

      <section aria-label="A new errand" className="card space-y-3 p-3 sm:p-4">
        <textarea
          ref={area}
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void submit();
          }}
          rows={3}
          placeholder="What should get done? “Reach Ana Lee at Acme Labs about the open role, by email, with my CV.”"
          className="w-full resize-none bg-transparent text-[15px] leading-relaxed text-ink placeholder:text-faint focus:outline-none"
        />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-muted">
            {busyErrand
              ? "One errand at a time: start the next when this one is done."
              : "It goes as far as it can and stops one tap short."}
          </p>
          <ActionButton
            icon={ArrowUp}
            label={starting ? "Starting…" : "Do it"}
            tone="accent"
            disabled={!canStart}
            onClick={() => void submit()}
          />
        </div>
      </section>

      {(busyErrand || working) && (
        <section aria-live="polite" className="card space-y-2 p-4 sm:p-5">
          <p className="smallcaps text-accent">Working on it</p>
          {working ? (
            <>
              <p className="text-sm leading-relaxed text-ink/90">{working.goal}</p>
              {working.steps.length > 0 && (
                <p className="text-sm text-muted">
                  {working.steps[working.steps.length - 1].title}
                  {data && ` · ${timeAgo(working.steps[working.steps.length - 1].at, data.now)}`}
                </p>
              )}
            </>
          ) : (
            <p className="text-sm text-muted">Reading the errand.</p>
          )}
        </section>
      )}

      {data === null ? (
        error ? null : (
          <div className="card space-y-3 p-5" aria-hidden="true">
            <Bone className="h-4 w-1/4" />
            <Bone className="h-4 w-full" />
            <Bone className="h-4 w-4/5" />
          </div>
        )
      ) : data.errands.filter((e) => e !== working).length === 0 ? (
        !busyErrand &&
        !working && (
          <p className="max-w-2xl text-sm leading-relaxed text-muted">
            Give it something to get done for you, like reaching someone about a role. It looks them up, finds a way to reach them from your
            own mail and chats (an address is never guessed), finds your newest CV, writes the message the way you&apos;ve written these
            before, and stops one tap short. You read what it did, step by step, and press Send. Nothing goes out unless you do. An errand
            still waiting on an address looks again each night.
          </p>
        )
      ) : (
        <section aria-label="Errands" className="space-y-4">
          <p className="smallcaps">Errands</p>
          {data.errands
            .filter((e) => e !== working)
            .map((e) => (
              <ErrandCard
                key={e.id}
                errand={e}
                now={data.now}
                busy={busySend}
                onSend={(index, edits) => void send(e.id, index, edits)}
                onDrop={() => void drop(e.id)}
              />
            ))}
        </section>
      )}
    </div>
  );
}
