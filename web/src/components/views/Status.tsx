"use client";

import { Activity, Database, FolderX, Hash, Mail, MessageCircle, Music, Radar, type LucideIcon } from "lucide-react";

import { EmptyState, ErrorBanner, LoadingRows } from "@/components/EmptyState";
import { useJson } from "@/lib/client";
import { formatDateTime, hoursSince, timeAgo } from "@/lib/format";
import type { SourceStatus, StatusResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

const SOURCE_STYLE: Record<string, { icon: LucideIcon; color: string }> = {
  whatsapp: { icon: MessageCircle, color: "text-green-600 bg-green-100" },
  spotify: { icon: Music, color: "text-emerald-700 bg-emerald-100" },
  strava: { icon: Activity, color: "text-orange-600 bg-orange-100" },
  email: { icon: Mail, color: "text-blue-600 bg-blue-100" },
  slack: { icon: Hash, color: "text-purple-600 bg-purple-100" },
};

function freshness(lastSync: string | null, now: string): { label: string; dot: string } {
  const h = hoursSince(lastSync, now);
  if (h < 6) return { label: "Fresh", dot: "bg-green-500" };
  if (h < 72) return { label: "Behind", dot: "bg-amber-400" };
  if (h < Infinity) return { label: "Stale", dot: "bg-gray-400" };
  return { label: "Never", dot: "bg-gray-300" };
}

function SourceRow({ s, now }: { s: SourceStatus; now: string }) {
  const style = SOURCE_STYLE[s.kind] ?? { icon: Database, color: "text-primary bg-primary/10" };
  const fresh = freshness(s.lastSync, now);
  return (
    <div className="bg-surface p-4 rounded-xl shadow-sm border border-gray-100 flex items-start gap-4">
      <div className={cn("p-3 rounded-full flex-shrink-0", style.color)}>
        <style.icon size={20} />
      </div>
      <div className="flex-1 min-w-0 pt-0.5">
        <div className="flex items-center justify-between gap-3">
          <span className="font-bold text-text-primary truncate">{s.id}</span>
          <span className="flex items-center gap-1.5 text-xs font-bold text-text-secondary whitespace-nowrap">
            <span className={cn("w-2 h-2 rounded-full", fresh.dot)} />
            {fresh.label}
          </span>
        </div>
        {s.lastSync ? (
          <div className="text-sm text-text-secondary space-y-0.5 mt-1">
            <div>
              Last sync {timeAgo(s.lastSync, now)} · {formatDateTime(s.lastSync)}
            </div>
            <div>
              {s.newestMonth}: {s.newestMonthLines.toLocaleString()} lines
              {s.newestMonthFiles > 1 && ` across ${s.newestMonthFiles} files`}
            </div>
          </div>
        ) : (
          <div className="text-sm text-text-secondary mt-1">
            Not synced yet. Run <code className="font-mono bg-gray-100 px-1.5 py-0.5 rounded">{s.command}</code>
          </div>
        )}
      </div>
    </div>
  );
}

export function Status() {
  const { data, error } = useJson<StatusResponse>("/api/status");

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load status: ${error}`} /> : <LoadingRows />;
  }

  if (!data.vault.exists) {
    return (
      <EmptyState icon={FolderX} title="No vault found" command="TWIN_VAULT=~/twin_vault">
        Looked in <code className="font-mono">{data.vault.path}</code>. Set TWIN_VAULT in the repo&apos;s .env or
        the environment, then reload.
      </EmptyState>
    );
  }

  const t = data.tracker;
  const synced = data.sources.filter((s) => s.lastSync).length;

  return (
    <div className="p-4 sm:p-6 pb-24 md:pb-20 space-y-8">
      <section className="bg-surface rounded-2xl p-5 sm:p-6 shadow-soft">
        <div className="flex items-center gap-3 mb-4">
          <div className="p-3 rounded-full text-yellow-700 bg-primary/20">
            <Radar size={20} />
          </div>
          <h2 className="font-bold text-xl text-text-primary">Tracker</h2>
        </div>
        {t.lastBatch ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: "Last batch", value: timeAgo(t.lastBatch, data.now), title: formatDateTime(t.lastBatch) },
              { label: "In last batch", value: t.lastBatchCount.toLocaleString() },
              { label: "Items, all time", value: t.items.toLocaleString() },
              { label: "Reactions logged", value: t.feedback.toLocaleString() },
            ].map((s) => (
              <div key={s.label} className="bg-background rounded-xl p-3 min-w-0" title={s.title}>
                <div className="text-2xl font-bold truncate">{s.value}</div>
                <div className="text-sm text-text-secondary">{s.label}</div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-text-secondary">
            No batches yet. Run{" "}
            <code className="font-mono bg-gray-100 px-1.5 py-0.5 rounded">twin clone tracker</code> to fetch and
            rank the first one.
          </p>
        )}
      </section>

      <section className="space-y-4">
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <h2 className="font-bold text-xl text-text-primary">Sources</h2>
          <span className="text-sm text-text-secondary">
            {synced} of {data.sources.length} synced
          </span>
        </div>
        {data.sources.map((s) => (
          <SourceRow key={s.id} s={s} now={data.now} />
        ))}
        <p className="text-xs text-text-secondary break-all">
          Vault: <code className="font-mono">{data.vault.path}</code>
        </p>
        <p className="text-xs text-text-secondary">
          Read from file names, modification times and line counts under <code className="font-mono">raw/</code>.
          Message contents are never read here.
        </p>
      </section>
    </div>
  );
}
