"use client";

import { useState } from "react";
import { PenLine, ShieldCheck } from "lucide-react";

import { DraftCard } from "@/components/drafts/DraftCard";
import { EmptyState, ErrorBanner, NoVault } from "@/components/EmptyState";
import { DraftSkeleton } from "@/components/Skeleton";
import { useDrafts } from "@/lib/client";
import { groupDrafts, isAwaiting } from "@/lib/drafts";
import { cn } from "@/lib/utils";

type Show = "awaiting" | "approved";

/** Proxenos acting as you: replies, emails, plans and docs it wrote, waiting for you to approve. */
export function Drafts({ onChange }: { onChange?: () => void }) {
  const { data, error, flashId, approve, discard, edit, copy, clearError } = useDrafts(onChange);
  const [show, setShow] = useState<Show>("awaiting");

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load the drafts: ${error}`} /> : <DraftSkeleton />;
  }
  if (!data.vault.exists) return <NoVault path={data.vault.path} />;

  const kept = data.drafts.filter((d) => d.status !== "discarded");
  const awaiting = kept.filter((d) => isAwaiting(d.status));
  const approved = kept.filter((d) => d.status === "approved");

  if (kept.length === 0) {
    return (
      <div className="pb-24 md:pb-20">
        {error && <ErrorBanner message={error} onDismiss={clearError} />}
        <EmptyState icon={PenLine} title="No drafts yet" command="proxenos clone work">
          Drafts appear when Proxenos works through your tasks, outreach, projects and reading: replies, emails, plans
          and notes written as you, waiting here for your approval. Nothing is ever sent for you.
        </EmptyState>
      </div>
    );
  }

  const shown = show === "awaiting" ? awaiting : approved;
  const groups = groupDrafts(shown);

  return (
    <div className="pb-24 md:pb-20">
      {error && <ErrorBanner message={error} onDismiss={clearError} />}

      <div className="px-4 sm:px-6 py-3 border-b border-line flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex gap-2">
          {(
            [
              ["awaiting", "Awaiting you", awaiting.length],
              ["approved", "Approved", approved.length],
            ] as const
          ).map(([id, label, n]) => (
            <button
              key={id}
              onClick={() => setShow(id)}
              aria-pressed={show === id}
              className={cn(
                "rounded-full border px-3 py-1 text-[13px] transition-colors whitespace-nowrap",
                show === id ? "border-accent/40 bg-accent/10 text-accent" : "border-line-strong text-muted hover:text-ink",
              )}
            >
              {label} <span className="num">{n}</span>
            </button>
          ))}
        </div>
        <p className="flex items-center gap-1.5 text-sm text-muted sm:ml-auto">
          <ShieldCheck size={15} className="text-ok-ink flex-shrink-0" />
          Nothing is sent from here. Copy a draft and send it yourself.
        </p>
      </div>

      {groups.length === 0 ? (
        <p className="px-4 sm:px-6 py-8 text-sm text-muted">
          {show === "awaiting" ? "Nothing is waiting for your approval." : "You haven't approved any drafts yet."}
        </p>
      ) : (
        <div className="p-4 sm:p-6 space-y-8">
          {groups.map((g) => (
            <section key={g.id} aria-labelledby={`drafts-${g.id}`}>
              <h2 id={`drafts-${g.id}`} className="font-display text-2xl text-ink mb-3 flex items-baseline gap-2">
                {g.label}
                <span className="num text-sm text-muted">{g.drafts.length}</span>
              </h2>
              <div className="grid gap-4 grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 items-start">
                {g.drafts.map((d) => (
                  <DraftCard
                    key={d.id}
                    draft={d}
                    now={data.now}
                    flash={flashId === d.id}
                    onCopy={copy}
                    onApprove={approve}
                    onDiscard={discard}
                    onEdit={edit}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
