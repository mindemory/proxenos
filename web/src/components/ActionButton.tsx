import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export type ActionTone = "ok" | "bad" | "warn" | "accent" | "neutral";

const ACTIVE: Record<ActionTone, string> = {
  ok: "border-ok-line bg-ok-bg text-ok-ink",
  bad: "border-bad-line bg-bad-bg text-bad-ink",
  warn: "border-warn-line bg-warn-bg text-warn-ink",
  accent: "border-accent/40 bg-accent/10 text-accent",
  neutral: "border-line-strong bg-surface-2 text-ink",
};

const HOVER: Record<ActionTone, string> = {
  ok: "hover:text-ok-ink hover:border-ok-line",
  bad: "hover:text-bad-ink hover:border-bad-line",
  warn: "hover:text-warn-ink hover:border-warn-line",
  accent: "hover:text-accent hover:border-accent/40",
  neutral: "hover:text-ink hover:bg-surface-2",
};

interface ActionButtonProps {
  icon: LucideIcon;
  label: string;
  tone: ActionTone;
  active?: boolean;
  fillWhenActive?: boolean;
  disabled?: boolean;
  onClick: () => void;
}

/** One pill-shaped action. Its pressed state is the record of what you chose. */
export function ActionButton({ icon: Icon, label, tone, active = false, fillWhenActive, disabled = false, onClick }: ActionButtonProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-pressed={active}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[13px] leading-none transition-colors whitespace-nowrap",
        "disabled:cursor-not-allowed disabled:opacity-50",
        active ? ACTIVE[tone] : cn("border-line-strong text-muted", HOVER[tone]),
      )}
    >
      <Icon size={14} strokeWidth={2.25} fill={fillWhenActive && active ? "currentColor" : "none"} />
      {label}
    </button>
  );
}
