import { Check, ThumbsDown, ThumbsUp, type LucideIcon } from "lucide-react";

import { ActionButton, type ActionTone } from "@/components/ActionButton";
import { formatDateTime, timeAgo } from "@/lib/format";
import type { GroupKind, NetworkAction, Relation } from "@/lib/types";

export const RELATION_LABEL: Record<Relation, string> = { met: "Met", know_of: "Know of", to_read: "To read" };

/** Tailwind classes for the relation's colour: a fill, a text colour, and a border. */
export const RELATION_STYLE: Record<Relation, { dot: string; text: string; border: string }> = {
  met: { dot: "bg-rel-met", text: "text-rel-met", border: "border-rel-met/40" },
  know_of: { dot: "bg-rel-know", text: "text-rel-know", border: "border-rel-know/40" },
  to_read: { dot: "bg-rel-read", text: "text-rel-read", border: "border-rel-read/40" },
};

export const KIND_LABEL: Record<GroupKind, string> = {
  whatsapp_group: "WhatsApp",
  slack_channel: "Slack",
  paper: "Papers",
  email_thread: "Email",
  org: "Orgs",
};

export const KIND_LABEL_ONE: Record<GroupKind, string> = {
  whatsapp_group: "WhatsApp group",
  slack_channel: "Slack channel",
  paper: "Paper",
  email_thread: "Email thread",
  org: "Organization",
};

const ACTIONS: { action: NetworkAction; label: string; icon: LucideIcon; tone: ActionTone; done: string }[] = [
  { action: "useful", label: "Useful", icon: ThumbsUp, tone: "ok", done: "You marked this useful" },
  { action: "not_me", label: "Not me", icon: ThumbsDown, tone: "bad", done: "You said this isn't for you" },
  { action: "done", label: "Done", icon: Check, tone: "ok", done: "You marked this done" },
];

export type Idea = { id: string; action: NetworkAction | null; acted_at: string | null };
export type OnReact = (item: Idea, action: NetworkAction) => void;

export function Label({ children }: { children: React.ReactNode }) {
  return <div className="eyebrow mb-1">{children}</div>;
}

/** The accent-tinted box for the one line to act on. */
export function Citation({ label, children, small = false }: { label: string; children: React.ReactNode; small?: boolean }) {
  return (
    <div className={small ? "rounded-xl border border-accent/25 bg-accent/[0.06] p-3" : "rounded-xl border border-accent/25 bg-accent/[0.06] p-4"}>
      <div className="text-[11px] leading-4 font-medium uppercase tracking-[0.08em] text-accent mb-1.5">{label}</div>
      <p className={small ? "font-display text-base leading-snug text-ink break-words" : "font-display text-lg leading-snug text-ink break-words"}>
        {children}
      </p>
    </div>
  );
}

export function Actions({ item, now, onReact }: { item: Idea; now: string; onReact: OnReact }) {
  const state = ACTIONS.find((a) => a.action === item.action);
  return (
    <div className="flex flex-wrap items-center gap-2">
      {ACTIONS.map((a) => (
        <ActionButton
          key={a.action}
          icon={a.icon}
          label={a.label}
          tone={a.tone}
          active={item.action === a.action}
          onClick={() => onReact(item, a.action)}
        />
      ))}
      {state && (
        <span className="text-xs text-muted sm:ml-auto">
          {state.done}
          {item.acted_at && (
            <>
              , <span className="num">{timeAgo(item.acted_at, now)}</span>
            </>
          )}
        </span>
      )}
    </div>
  );
}

export function Generated({ at, now, children }: { at: string | null; now: string; children?: React.ReactNode }) {
  return (
    <div className="px-4 sm:px-6 py-3 border-b border-line flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-sm text-muted">
      <span>{children}</span>
      {at && (
        <span title={formatDateTime(at)}>
          Generated <span className="num">{timeAgo(at, now)}</span>
        </span>
      )}
    </div>
  );
}
