"use client";

import { Radar } from "lucide-react";

import { Command, ErrorBanner, NoVault } from "@/components/EmptyState";
import { StatusSkeleton } from "@/components/Skeleton";
import { SourceChip, sourceMeta } from "@/components/SourceBadge";
import { useJson } from "@/lib/client";
import { formatDateTime, freshness, joinAnd, timeAgo } from "@/lib/format";
import type { SourceStatus, StatusResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

function SourceRow({ s, now }: { s: SourceStatus; now: string }) {
  const fresh = freshness(s.lastSync, now);
  return (
    <div className="card flex items-start gap-3.5 px-4 py-3.5">
      <SourceChip kind={s.kind} size={36} />
      <div className="flex-1 min-w-0 pt-0.5">
        <div className="flex items-center justify-between gap-3">
          <span className="min-w-0 truncate font-medium text-ink">
            {sourceMeta(s.kind).label}
            {s.id !== s.kind && <span className="num ml-2 text-xs font-normal text-muted">{s.id}</span>}
          </span>
          <span className={cn("flex items-center gap-1.5 text-xs whitespace-nowrap", fresh.text)}>
            <span className={cn("w-2 h-2 rounded-full", fresh.dot)} />
            {fresh.label}
          </span>
        </div>
        {s.lastSync ? (
          <div className="text-sm text-muted space-y-0.5 mt-1">
            <div>
              Last sync <span className="num">{timeAgo(s.lastSync, now)}</span> ·{" "}
              <span className="num">{formatDateTime(s.lastSync)}</span>
            </div>
            <div>
              <span className="num">{s.newestMonth}</span>: <span className="num">{s.newestMonthLines.toLocaleString()}</span>{" "}
              lines
              {s.newestMonthFiles > 1 && (
                <>
                  {" "}
                  across <span className="num">{s.newestMonthFiles}</span> files
                </>
              )}
            </div>
          </div>
        ) : (
          <div className="text-sm text-muted mt-1">
            Not synced yet. Run <Command>{s.command}</Command>
          </div>
        )}
      </div>
    </div>
  );
}

export function Status() {
  const { data, error } = useJson<StatusResponse>("/api/status");

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load status: ${error}`} /> : <StatusSkeleton />;
  }

  if (!data.vault.exists) return <NoVault path={data.vault.path} />;

  const t = data.tracker;
  const synced = data.sources.filter((s) => s.lastSync).length;

  return (
    <div className="p-4 sm:p-6 pb-24 md:pb-20 space-y-8">
      <section className="card p-5 sm:p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="p-2.5 rounded-full text-accent bg-accent/10">
            <Radar size={17} />
          </div>
          <div>
            <p className="smallcaps">Research feed</p>
            <h2 className="title-2">Tracker</h2>
          </div>
        </div>
        {t.lastBatch ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            {[
              { label: "Last batch", value: timeAgo(t.lastBatch, data.now), title: formatDateTime(t.lastBatch) },
              { label: "In last batch", value: t.lastBatchCount.toLocaleString() },
              { label: "Items, all time", value: t.items.toLocaleString() },
              { label: "Reactions logged", value: t.feedback.toLocaleString() },
            ].map((s) => (
              <div key={s.label} className="bg-bg border border-line rounded-xl px-3 py-2.5 min-w-0" title={s.title}>
                <div className="num text-xl truncate">{s.value}</div>
                <div className="text-xs text-muted">{s.label}</div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-muted">
            No batches yet. Run <Command>proxenos clone tracker</Command> to fetch and rank the first one.
          </p>
        )}
      </section>

      <section className="space-y-3">
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <div>
            <p className="smallcaps">Raw data</p>
            <h2 className="title-2">Sources</h2>
          </div>
          <span className="text-sm text-muted">
            <span className="num">{synced}</span> of <span className="num">{data.sources.length}</span> synced
          </span>
        </div>
        {data.sources.map((s) => (
          <SourceRow key={s.id} s={s} now={data.now} />
        ))}
        {data.missing.length > 0 && (
          <p className="text-sm text-muted px-1 leading-relaxed">
            Not set up: {joinAnd(data.missing.map((m) => sourceMeta(m).label))}. Each one appears here after its first{" "}
            <Command>proxenos ingest &lt;source&gt;</Command>
          </p>
        )}
        <p className="text-xs text-muted break-all px-1 pt-2">
          Vault: <code className="num">{data.vault.path}</code>
        </p>
        <p className="text-xs text-muted px-1">
          Read from file names, modification times and line counts under <code className="num">raw/</code>. Message
          contents are never read here.
        </p>
      </section>
    </div>
  );
}
