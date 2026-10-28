"use client";

import { UserRound } from "lucide-react";

import { Command, EmptyState, ErrorBanner, LoadingRows, NoVault } from "@/components/EmptyState";
import { Markdown } from "@/components/Markdown";
import { useJson } from "@/lib/client";
import { fileTitle, formatDateTime, timeAgo } from "@/lib/format";
import type { TwinResponse } from "@/lib/types";

export function Twin() {
  const { data, error } = useJson<TwinResponse>("/api/twin");

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load the profile: ${error}`} /> : <LoadingRows />;
  }

  if (!data.vault.exists) return <NoVault path={data.vault.path} />;

  if (data.files.length === 0) {
    return (
      <EmptyState icon={UserRound} title="No profile yet" command="twin master">
        The twin&apos;s picture of you lives in <code className="num">self/</code> in the vault: identity, interests,
        taste, voice, routines and open questions. <code className="num">twin master</code> builds it from your
        observations and reactions.
      </EmptyState>
    );
  }

  return (
    <div className="p-4 sm:p-6 pb-24 md:pb-20 space-y-5">
      <p className="text-sm text-muted">
        Read-only. <Command>twin master</Command> is the only writer of <code className="num">self/</code>.
      </p>

      <div className="flex flex-wrap gap-2">
        {data.files.map((f) => (
          <a
            key={f.name}
            href={`#self-${f.name}`}
            className="px-3 py-1 rounded-full bg-surface border border-line text-sm text-ink hover:border-accent/40 hover:text-accent transition-colors"
          >
            {fileTitle(f.name)}
          </a>
        ))}
      </div>

      {data.files.map((f) => (
        <section
          key={f.name}
          id={`self-${f.name}`}
          className="bg-surface border border-line rounded-2xl p-5 sm:p-6 scroll-mt-20"
        >
          <div className="flex items-baseline justify-between gap-3 mb-4 flex-wrap">
            <span className="num text-xs text-muted">{f.name}</span>
            <span className="text-xs text-muted" title={formatDateTime(f.mtime)}>
              Updated <span className="num">{timeAgo(f.mtime, data.now)}</span>
            </span>
          </div>
          {f.content.trim() ? <Markdown source={f.content} /> : <p className="text-muted">Empty file.</p>}
        </section>
      ))}
    </div>
  );
}
