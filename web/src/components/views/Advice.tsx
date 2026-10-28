"use client";

import { useState } from "react";
import { Lightbulb } from "lucide-react";

import { Command, EmptyState, ErrorBanner, LoadingRows, NoVault } from "@/components/EmptyState";
import { SuggestionCard } from "@/components/advice/SuggestionCard";
import { useAdvice } from "@/lib/client";
import { formatDateTime, shortDate, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

export function Advice({ onChange }: { onChange?: () => void }) {
  const [date, setDate] = useState<string | null>(null);
  const { data, error, flashId, react, clearError } = useAdvice(date, onChange);

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load advice: ${error}`} /> : <LoadingRows />;
  }

  if (!data.vault.exists) return <NoVault path={data.vault.path} />;

  if (!data.date) {
    return (
      <EmptyState icon={Lightbulb} title="No advice yet" command="twin clone advisor">
        The advisor compares what you do with what your profile says you want, and suggests one change at a time. It
        writes advice once the profile exists, so run <code className="num">twin master</code> first if the Twin view is
        empty.
      </EmptyState>
    );
  }

  const switching = date !== null && data.date !== date;
  const unanswered = data.suggestions.filter((s) => s.action === null).length;

  return (
    <div className="pb-24 md:pb-20">
      {error && <ErrorBanner message={error} onDismiss={clearError} />}

      <div className="px-4 sm:px-6 py-3 border-b border-line flex flex-wrap items-center justify-between gap-x-4 gap-y-2 text-sm text-muted">
        <label className="inline-flex items-center gap-2">
          <span>Advice from</span>
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
              Generated <span className="num">{timeAgo(data.generated, data.now)}</span> ·{" "}
            </span>
          )}
          <span className="num">{unanswered}</span> of <span className="num">{data.suggestions.length}</span> not
          answered
        </span>
      </div>

      <div className={cn("p-4 sm:p-6 space-y-4 transition-opacity", switching && "opacity-50")} aria-busy={switching}>
        {data.suggestions.length > 0 ? (
          data.suggestions.map((s) => (
            <SuggestionCard key={s.id} s={s} now={data.now} onReact={react} flash={flashId === s.id} />
          ))
        ) : (
          <p className="text-sm text-muted">
            This file has no suggestions. <Command>twin clone advisor</Command> writes a new one.
          </p>
        )}
        <p className="text-xs text-muted pt-2">
          Each answer is appended to <code className="num">clones/advisor/feedback.jsonl</code> in the vault.
        </p>
      </div>
    </div>
  );
}
