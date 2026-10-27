"use client";

import { UserRound } from "lucide-react";

import { EmptyState, ErrorBanner, LoadingRows } from "@/components/EmptyState";
import { Markdown } from "@/components/Markdown";
import { useJson } from "@/lib/client";
import { fileTitle, formatDateTime, timeAgo } from "@/lib/format";
import type { TwinResponse } from "@/lib/types";

export function Twin() {
  const { data, error } = useJson<TwinResponse>("/api/twin");

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load the profile: ${error}`} /> : <LoadingRows />;
  }

  if (data.files.length === 0) {
    return (
      <EmptyState icon={UserRound} title="No profile yet" command="twin master">
        The twin&apos;s picture of you lives in <code className="font-mono">self/</code> in the vault: identity,
        interests, taste, voice, routines and open questions. <code className="font-mono">twin master</code> builds
        it from your observations and reactions.
      </EmptyState>
    );
  }

  return (
    <div className="p-4 sm:p-6 pb-24 md:pb-20 space-y-6">
      <p className="text-sm text-text-secondary">
        Read-only. <code className="font-mono">twin master</code> is the only writer of{" "}
        <code className="font-mono">self/</code>.
      </p>

      <div className="flex flex-wrap gap-2">
        {data.files.map((f) => (
          <a
            key={f.name}
            href={`#self-${f.name}`}
            className="px-3 py-1 rounded-full bg-surface border border-gray-100 text-sm font-medium hover:bg-primary/20 transition-colors"
          >
            {fileTitle(f.name)}
          </a>
        ))}
      </div>

      {data.files.map((f) => (
        <section
          key={f.name}
          id={`self-${f.name}`}
          className="bg-surface rounded-2xl p-5 sm:p-6 shadow-soft scroll-mt-24"
        >
          <div className="flex items-baseline justify-between gap-3 mb-4 flex-wrap">
            <span className="text-xs font-bold uppercase tracking-wider text-zinc-500">{f.name}</span>
            <span className="text-xs text-text-secondary" title={formatDateTime(f.mtime)}>
              Updated {timeAgo(f.mtime, data.now)}
            </span>
          </div>
          {f.content.trim() ? (
            <Markdown source={f.content} />
          ) : (
            <p className="text-text-secondary">Empty file.</p>
          )}
        </section>
      ))}
    </div>
  );
}
