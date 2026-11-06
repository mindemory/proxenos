"use client";

import { Route } from "lucide-react";

import { Fold } from "@/components/ask/parts";
import type { ErrandItem } from "@/lib/drafts";
import { timeAgo } from "@/lib/format";
import type { Draft, ErrandEdits } from "@/lib/types";

import { MessageBox } from "./ErrandCard";

interface ErrandMessageCardProps {
  item: ErrandItem;
  now: string;
  /** A Send, Mark sent or Done is going. */
  busy: boolean;
  /** The same thing waiting as a draft, older than this message: shown folded under it. */
  under: Draft | null;
  onSend: (edits: ErrandEdits) => void;
  onMarkSent: () => void;
  onMarkDone: () => void;
  /** Open the errand's steps. */
  onErrand?: (id: string) => void;
}

/**
 * An errand's message waiting to be sent, in the Drafts list with the rest: where it came from
 * (the errand's goal, and its steps), and the message with Send, Copy, Mark sent and Done.
 */
export function ErrandMessageCard({ item, now, busy, under, onSend, onMarkSent, onMarkDone, onErrand }: ErrandMessageCardProps) {
  const { errand, message } = item;
  return (
    <article id={`errand-message-${errand.id}-${item.index}`} className="card flex min-w-0 scroll-mt-20 flex-col gap-3 p-4 sm:p-5">
      <div className="min-w-0 space-y-1">
        <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted">
          <Route size={13} aria-hidden="true" />
          <span className="smallcaps">From an errand</span>
          {errand.created && <span className="num">{timeAgo(errand.created, now)}</span>}
          {onErrand && (
            <button onClick={() => onErrand(errand.id)} className="text-accent hover:underline underline-offset-4">
              See its steps
            </button>
          )}
        </p>
        <p className="line-clamp-3 break-words text-sm leading-relaxed text-ink/90">{errand.goal}</p>
      </div>

      <MessageBox
        // A change on the server (a Send, a night's look for an address) starts the box afresh.
        key={`${item.index}-${errand.updated}`}
        message={message}
        cv={errand.cv}
        busy={busy}
        onSend={onSend}
        onMarkSent={onMarkSent}
        onMarkDone={onMarkDone}
      />

      {under && (
        <Fold label={`Also a draft: ${under.title}`}>
          <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-ink/80">{under.body}</p>
        </Fold>
      )}
    </article>
  );
}
