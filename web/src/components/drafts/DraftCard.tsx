"use client";

import { useRef, useState } from "react";
import { Check, ChevronDown, Copy, Pencil, Trash2, X } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { Markdown } from "@/components/Markdown";
import { formatDateTime, timeAgo } from "@/lib/format";
import { isAwaiting } from "@/lib/drafts";
import type { Draft } from "@/lib/types";
import { cn } from "@/lib/utils";

import { ChannelBadge, KindBadge } from "./badges";

// Long drafts are clipped until asked for, so a page of them stays scannable.
const CLIP_CHARS = 700;

interface DraftCardProps {
  draft: Draft;
  now: string;
  flash: boolean;
  onCopy: (d: Draft) => void;
  onApprove: (d: Draft) => void;
  onDiscard: (d: Draft) => void;
  /** Resolves true when the new body is saved. */
  onEdit: (d: Draft, body: string) => Promise<boolean>;
}

export function DraftCard({ draft: d, now, flash, onCopy, onApprove, onDiscard, onEdit }: DraftCardProps) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  const approved = d.status === "approved";
  const long = d.body.length > CLIP_CHARS;

  const start = () => {
    setText(d.body);
    setEditing(true);
    // After the textarea mounts.
    window.setTimeout(() => area.current?.focus(), 0);
  };

  const save = async () => {
    if (saving) return;
    setSaving(true);
    const ok = await onEdit(d, text);
    setSaving(false);
    if (ok) setEditing(false);
  };

  return (
    <article
      className={cn(
        "bg-surface border rounded-2xl p-4 sm:p-5 flex flex-col gap-3 min-w-0 transition-colors",
        approved ? "border-ok-line/60" : "border-line",
        flash && "row-flash",
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <KindBadge kind={d.kind} />
        <ChannelBadge channel={d.channel} />
        <span
          className={cn(
            "ml-auto inline-flex items-center gap-1 text-xs",
            approved ? "text-ok-ink" : isAwaiting(d.status) ? "text-muted" : "text-muted/70",
          )}
        >
          {approved && <Check size={12} />}
          {approved ? "Approved" : isAwaiting(d.status) ? "Awaiting you" : d.status}
        </span>
      </div>

      <div className="min-w-0">
        <h3 className="font-display text-xl leading-snug text-ink break-words">{d.title}</h3>
        <p className="text-sm text-muted mt-0.5 break-words">
          {d.to ? (
            <>
              To <span className="text-ink/90">{d.to}</span>
            </>
          ) : (
            "Not addressed to anyone"
          )}
          {d.created && (
            <span title={formatDateTime(d.created)}>
              {" "}
              · written <span className="num">{timeAgo(d.created, now)}</span>
            </span>
          )}
        </p>
      </div>

      {editing ? (
        <div className="space-y-2">
          <label className="block">
            <span className="sr-only">Draft text</span>
            <textarea
              ref={area}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") setEditing(false);
                else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  void save();
                }
              }}
              rows={Math.min(18, Math.max(6, text.split("\n").length + 1))}
              spellCheck
              className="w-full rounded-xl border border-line-strong bg-bg p-3 text-sm text-ink leading-relaxed resize-y font-sans"
            />
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <ActionButton icon={Check} label={saving ? "Saving" : "Save"} tone="accent" active onClick={() => void save()} />
            <ActionButton icon={X} label="Cancel" tone="neutral" onClick={() => setEditing(false)} />
            <span className="text-xs text-muted sm:ml-auto">Saved to the draft&apos;s file. ⌘↵ saves, Esc cancels.</span>
          </div>
        </div>
      ) : (
        <div className="relative min-w-0">
          <div className={cn(long && !expanded && "max-h-56 overflow-hidden")}>
            {d.body ? <Markdown source={d.body} compact /> : <p className="text-sm text-muted">This draft has no text.</p>}
          </div>
          {long && !expanded && (
            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-surface to-transparent" />
          )}
          {long && (
            <button
              onClick={() => setExpanded((v) => !v)}
              aria-expanded={expanded}
              className="relative mt-1 inline-flex items-center gap-1 text-xs text-accent hover:underline underline-offset-4"
            >
              <ChevronDown size={13} className={cn("transition-transform", expanded && "rotate-180")} />
              {expanded ? "Show less" : "Show all"}
            </button>
          )}
        </div>
      )}

      {!editing && (
        <div className="flex flex-wrap gap-2 pt-1 mt-auto">
          <ActionButton icon={Copy} label="Copy" tone="accent" onClick={() => onCopy(d)} />
          <ActionButton icon={Check} label={approved ? "Approved" : "Approve"} tone="ok" active={approved} onClick={() => onApprove(d)} />
          <ActionButton icon={Pencil} label="Edit" tone="neutral" onClick={start} />
          <ActionButton icon={Trash2} label="Discard" tone="bad" onClick={() => onDiscard(d)} />
        </div>
      )}
    </article>
  );
}
