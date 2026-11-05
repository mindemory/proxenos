"use client";

import { useRef, useState } from "react";
import { Check, CheckCheck, ChevronDown, Copy, MessagesSquare, Pencil, RotateCcw, Trash2, X } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { Markdown } from "@/components/Markdown";
import { Listen } from "@/components/reading/Listen";
import { openTarget } from "@/lib/actions";
import { formatDateTime, timeAgo } from "@/lib/format";
import type { Draft, DraftOpen } from "@/lib/types";
import { cn } from "@/lib/utils";

import { ChannelBadge, KindBadge, SentBadge } from "./badges";
import { AltOpenLink, OpenButton, SentPrompt } from "./OpenAction";

// Long drafts are clipped until asked for, so a page of them stays scannable.
const CLIP_CHARS = 700;

interface DraftCardProps {
  draft: Draft;
  now: string;
  flash: boolean;
  /** Where the draft opens, or null for one that's already sent. */
  plan: DraftOpen | null;
  onCopy: (d: Draft) => void;
  onDiscard: (d: Draft) => void;
  /** Opens the draft in its app (or its second way in, for `viaAlt`). Resolves true once it has. */
  onOpen: (d: Draft, viaAlt: boolean) => Promise<boolean>;
  /** The reader says they sent it. */
  onSent: (d: Draft) => void;
  /** Resolves true when the new body is saved. */
  onEdit: (d: Draft, body: string) => Promise<boolean>;
  /** The reader says an overtaken draft is still needed. */
  onKeep: (d: Draft) => void;
  /** Asks "Is this still needed?" of a draft no thread backs that has waited a week: Keep (asked again in a week) or Done. */
  check?: { onKeep: (d: Draft) => void; onDone: (d: Draft) => void };
  /** The draft someone opened from another view (the home page): shown whole and highlighted. */
  focused?: boolean;
  /** Think it through with Proxenos before sending it. */
  onThink?: (d: Draft) => void;
}

export function DraftCard({ draft: d, now, flash, plan, onCopy, onDiscard, onOpen, onSent, onEdit, onKeep, check, focused, onThink }: DraftCardProps) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [expanded, setExpanded] = useState(focused ?? false);
  const [asking, setAsking] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  const sent = d.status === "sent";
  const overtaken = d.status === "overtaken";
  const long = d.body.length > CLIP_CHARS;
  const isEmail = openTarget(d) === "email";

  const start = () => {
    setText(d.body);
    setEditing(true);
    // After the textarea mounts.
    window.setTimeout(() => area.current?.focus(), 0);
  };

  const open = async (viaAlt: boolean) => {
    if (await onOpen(d, viaAlt)) setAsking(true);
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
      id={`draft-${d.id}`}
      className={cn(
        "card card-hover flex min-w-0 scroll-mt-20 flex-col gap-3 p-4 sm:p-5",
        (flash || focused) && "row-flash",
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <KindBadge kind={d.kind} />
        <ChannelBadge channel={d.channel} />
        <span className="ml-auto flex items-center gap-1.5 empty:hidden">
          {!editing && <Listen id={`draft:${d.id}`} text={d.body} what={d.title} />}
          {sent && <SentBadge />}
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
        {isEmail && (
          <p
            className="text-sm text-muted mt-0.5 break-words"
            title="The mailbox its thread is on: open it from there, so a reply doesn't start a new conversation from another address."
          >
            Reply from:{" "}
            {d.fromAddress ? (
              <span className="text-ink/90">{d.fromAddress}</span>
            ) : (
              <span>not recorded for this draft, so check the From line</span>
            )}
          </p>
        )}
      </div>

      {overtaken && (
        <p className="rounded-xl border border-line-strong bg-bg px-3 py-2 text-sm leading-relaxed text-ink/90">
          <span className="font-medium text-ink">No longer needed: </span>
          {d.overtaken || "the messages since show it isn't."}
        </p>
      )}

      {check && !sent && !overtaken && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-warn-line bg-warn-bg px-3 py-2 text-sm text-warn-ink">
          <span className="font-medium">Is this still needed?</span>
          <span className="ml-auto flex gap-2">
            <ActionButton icon={RotateCcw} label="Keep" tone="accent" onClick={() => check.onKeep(d)} />
            <ActionButton icon={Check} label="Done" tone="neutral" onClick={() => check.onDone(d)} />
          </span>
        </div>
      )}

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
            <span className="text-xs text-muted sm:ml-auto">Later drafts learn from what you change. ⌘↵ saves, Esc cancels.</span>
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
          {(d.found || d.asks.length > 0) && (
            <div className="mt-3 space-y-2 border-l-2 border-line-strong pl-3 text-xs leading-relaxed text-muted">
              {d.found && (
                <p>
                  <span className="font-medium text-ink">What it looked up: </span>
                  {d.found}
                </p>
              )}
              {d.asks.length > 0 && (
                <div>
                  <p className="font-medium text-ink">Needs from you</p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-4">
                    {d.asks.map((ask) => (
                      <li key={ask}>{ask}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {!editing && (
        <div className="flex flex-wrap items-center gap-2 pt-1 mt-auto">
          {sent ? (
            <ActionButton icon={Copy} label="Copy" tone="neutral" onClick={() => onCopy(d)} />
          ) : overtaken ? (
            <>
              <ActionButton icon={RotateCcw} label="Still needed" tone="accent" onClick={() => onKeep(d)} />
              <ActionButton icon={Copy} label="Copy" tone="neutral" onClick={() => onCopy(d)} />
              <ActionButton icon={Trash2} label="Discard" tone="bad" onClick={() => onDiscard(d)} />
            </>
          ) : (
            <>
              {plan && <OpenButton plan={plan} primary onOpen={() => void open(false)} />}
              <ActionButton icon={Copy} label="Copy" tone={plan ? "neutral" : "accent"} onClick={() => onCopy(d)} />
              <ActionButton icon={CheckCheck} label="I sent it" tone="ok" onClick={() => onSent(d)} />
              <ActionButton icon={Pencil} label="Write my own" tone="neutral" onClick={start} />
              {onThink && <ActionButton icon={MessagesSquare} label="Think it through" tone="neutral" onClick={() => onThink(d)} />}
              <ActionButton icon={Trash2} label="Discard" tone="bad" onClick={() => onDiscard(d)} />
            </>
          )}
        </div>
      )}

      {!editing && !sent && !overtaken && plan?.alt && !asking && (
        <p className="-mt-1 text-xs text-muted">
          Another way: <AltOpenLink plan={plan} onOpen={() => void open(true)} />
        </p>
      )}

      {!editing && asking && plan && !sent && (
        <SentPrompt
          onSent={() => {
            setAsking(false);
            onSent(d);
          }}
          onNotYet={() => setAsking(false)}
        />
      )}
    </article>
  );
}
