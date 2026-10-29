"use client";

import { useEffect, useState } from "react";
import { ArrowRight, Brain, Check, Copy, Route, TriangleAlert } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { ChannelBadge } from "@/components/drafts/badges";
import { Markdown } from "@/components/Markdown";
import { useToast } from "@/components/Toasts";
import { copyText } from "@/lib/client";
import { formatDateTime, timeAgo } from "@/lib/format";
import type { AskDraft, AskEntry } from "@/lib/types";
import { cn } from "@/lib/utils";

import { Fold, QuestionText, ShotCount } from "./parts";

/** The reply written in the reader's voice: its text as it'll be copied, and where else it is. */
function DraftBox({ draft, onDrafts }: { draft: AskDraft; onDrafts: () => void }) {
  const notify = useToast();
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1600);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const copy = async () => {
    const ok = await copyText(draft.body);
    setFailed(!ok);
    if (!ok) return;
    notify("Copied to the clipboard", "ok");
    setCopied(true);
  };

  return (
    <div className="rounded-xl border border-line-strong bg-surface-2 p-3.5 sm:p-4">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        <span className="smallcaps">Draft reply</span>
        <ChannelBadge channel={draft.channel} />
        {draft.to && (
          <span className="min-w-0 break-words text-sm text-muted">
            To <span className="text-ink/90">{draft.to}</span>
          </span>
        )}
      </div>
      <p className="mt-2.5 whitespace-pre-wrap break-words text-sm leading-relaxed text-ink">{draft.body}</p>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
        <ActionButton icon={copied ? Check : Copy} label={copied ? "Copied" : "Copy"} tone="accent" active={copied} onClick={() => void copy()} />
        <button
          onClick={onDrafts}
          className="inline-flex items-center gap-1 text-xs text-accent underline-offset-4 hover:underline"
        >
          Also in Drafts
          <ArrowRight size={13} aria-hidden="true" />
        </button>
      </div>
      {failed && <p className="mt-2 text-xs text-bad-ink">Couldn&apos;t reach the clipboard. Select the text and copy it by hand.</p>}
    </div>
  );
}

interface AskCardProps {
  ask: AskEntry;
  now: string;
  flash: boolean;
  onDrafts: () => void;
  /** Think this quick answer through; null while another ask is going. */
  onAgain: (() => void) | null;
  /** Hand it to an errand, to carry out what the answer says to do. */
  onErrand: () => void;
}

/** One question and what came of it, newest first on the page. */
export function AskCard({ ask, now, flash, onDrafts, onAgain, onErrand }: AskCardProps) {
  const failed = ask.status === "failed";
  const working = ask.status === "working";
  return (
    <article
      id={`ask-${ask.id}`}
      className={cn("card flex min-w-0 scroll-mt-20 flex-col gap-4 p-4 sm:p-5", flash && "row-flash")}
    >
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
          <span className="smallcaps text-faint">You asked</span>
          {ask.at && (
            <span className="text-xs text-muted" title={formatDateTime(ask.at)}>
              <span className="num">{timeAgo(ask.at, now)}</span>
            </span>
          )}
          <ShotCount n={ask.images} />
          {!ask.deep && <span className="text-xs text-faint">Quick answer</span>}
        </div>
        {ask.question ? (
          <QuestionText text={ask.question} />
        ) : (
          ask.images > 0 && <p className="text-sm text-muted">Only screenshots.</p>
        )}
      </div>

      {ask.seen && (
        <Fold label="What it saw">
          <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-muted">{ask.seen}</p>
        </Fold>
      )}

      {working && <p className="text-sm text-muted">Still thinking it through.</p>}

      {failed && (
        <div className="flex items-start gap-2.5 rounded-xl border border-bad-line bg-bad-bg p-3 text-sm text-bad-ink">
          <TriangleAlert size={16} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
          <span className="min-w-0 break-words">{ask.error ?? "It didn't finish."}</span>
        </div>
      )}

      {ask.answer && <Markdown source={ask.answer} />}

      {ask.draft && <DraftBox draft={ask.draft} onDrafts={onDrafts} />}

      {(ask.found || ask.asks.length > 0) && (
        <div className="space-y-2 border-l-2 border-line-strong pl-3 text-xs leading-relaxed text-muted">
          {ask.found && (
            <p>
              <span className="font-medium text-ink">What it looked up: </span>
              {ask.found}
            </p>
          )}
          {ask.asks.length > 0 && (
            <div>
              <p className="font-medium text-ink">Needs from you</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                {ask.asks.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {ask.status === "done" && (
        <div className="flex flex-wrap gap-2">
          {!ask.deep && <ActionButton icon={Brain} label="Think it through" tone="neutral" disabled={!onAgain} onClick={() => onAgain?.()} />}
          <ActionButton icon={Route} label="Do it for me" tone="neutral" onClick={onErrand} />
        </div>
      )}
    </article>
  );
}
