"use client";

import { Check, Download, ExternalLink, Hash, Mail, MessageCircle, X, type LucideIcon } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import type { DraftOpen, OpenTarget } from "@/lib/types";
import { cn } from "@/lib/utils";

const ICON: Record<OpenTarget, LucideIcon> = {
  gmail: Mail,
  whatsapp: MessageCircle,
  slack: Hash,
  linkedin: ExternalLink,
  instagram: MessageCircle,
  messenger: MessageCircle,
  file: Download,
};

interface OpenButtonProps {
  plan: DraftOpen;
  /** The main action of an approved draft: filled in. Otherwise it's a quiet one beside Approve. */
  primary: boolean;
  onOpen: () => void;
}

/** Opens the draft in the app it's for, with its text filled in. The reader presses send there. */
export function OpenButton({ plan, primary, onOpen }: OpenButtonProps) {
  const Icon = ICON[plan.target];
  return (
    <button
      onClick={onOpen}
      title={plan.hint}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[13px] leading-none transition-colors whitespace-nowrap",
        primary
          ? "border-accent bg-accent text-accent-ink font-medium hover:bg-accent/85"
          : "border-line-strong text-muted hover:text-ink hover:bg-surface-2",
      )}
    >
      <Icon size={14} strokeWidth={2.25} />
      {plan.label}
    </button>
  );
}

/** The second way in, where there is one: an email can also go to the default mail app. */
export function AltOpenLink({ plan, onOpen }: { plan: DraftOpen; onOpen: () => void }) {
  if (!plan.alt) return null;
  return (
    <button
      onClick={onOpen}
      title={plan.alt.hint}
      className="text-accent underline-offset-4 hover:underline"
    >
      {plan.alt.label}
    </button>
  );
}

/**
 * Asked once a draft has gone to its app. Proxenos can't see whether the reader pressed send
 * there, so it asks, and only "Mark sent" changes the draft.
 */
export function SentPrompt({ onSent, onNotYet }: { onSent: () => void; onNotYet: () => void }) {
  return (
    <div
      role="group"
      aria-label="Did you send it?"
      className="flex flex-wrap items-center gap-2 rounded-xl border border-line-strong bg-surface-2 px-3 py-2"
    >
      <span className="text-sm text-ink">Sent?</span>
      <ActionButton icon={Check} label="Mark sent" tone="ok" onClick={onSent} />
      <ActionButton icon={X} label="Not yet" tone="neutral" onClick={onNotYet} />
      <span className="text-xs text-muted sm:ml-auto">You press send in the app, then say so here.</span>
    </div>
  );
}
