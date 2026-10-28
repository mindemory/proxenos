import { Hash, Play, ThumbsDown, ThumbsUp, type LucideIcon } from "lucide-react";

import { ActionButton, type ActionTone } from "@/components/ActionButton";
import { timeAgo } from "@/lib/format";
import type { AdviceAction, Confidence, SuggestionView } from "@/lib/types";
import { cn } from "@/lib/utils";

const CONFIDENCE: Record<Confidence, string> = {
  high: "border-ok-line bg-ok-bg text-ok-ink",
  medium: "border-warn-line bg-warn-bg text-warn-ink",
  low: "border-line-strong bg-surface-2 text-muted",
};

export const ADVICE_ACTION_META: Record<AdviceAction, { label: string; icon: LucideIcon; tone: ActionTone; done: string }> = {
  useful: { label: "Useful", icon: ThumbsUp, tone: "ok", done: "You marked this useful" },
  not_me: { label: "Not me", icon: ThumbsDown, tone: "bad", done: "You said this isn't you" },
  doing: { label: "Doing it", icon: Play, tone: "accent", done: "You're doing this" },
};

interface SuggestionCardProps {
  s: SuggestionView;
  now: string;
  actions?: readonly AdviceAction[];
  onReact: (s: SuggestionView, action: AdviceAction) => void;
  /** Home shows pattern and suggestion only. */
  compact?: boolean;
  flash?: boolean;
}

function Label({ children }: { children: React.ReactNode }) {
  return <div className="eyebrow mb-1">{children}</div>;
}

export function SuggestionCard({
  s,
  now,
  actions = ["useful", "not_me", "doing"],
  onReact,
  compact = false,
  flash = false,
}: SuggestionCardProps) {
  return (
    <article
      className={cn(
        "bg-surface border border-line rounded-2xl p-4 sm:p-5 space-y-4 transition-opacity",
        flash && "row-flash",
        s.action === "not_me" && "opacity-60 hover:opacity-90",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="inline-flex items-center gap-1 rounded-md bg-surface-2 px-2 py-0.5 text-xs text-ink/85 min-w-0">
          <Hash size={12} className="flex-shrink-0" />
          <span className="truncate">{s.area}</span>
        </span>
        <span className={cn("rounded-full border px-2 py-0.5 text-xs whitespace-nowrap", CONFIDENCE[s.confidence])}>
          {s.confidence[0].toUpperCase() + s.confidence.slice(1)} confidence
        </span>
      </div>

      {s.pattern && (
        <div>
          <Label>What you do now</Label>
          <p className={cn("text-sm text-muted leading-relaxed break-words", compact && "line-clamp-3")}>{s.pattern}</p>
        </div>
      )}

      {/* The citation card: the one thing to take away. */}
      <div className="rounded-xl border border-accent/25 bg-accent/[0.06] p-4">
        <div className="text-[11px] leading-4 font-medium uppercase tracking-[0.08em] text-accent mb-1.5">Try instead</div>
        <p className="font-display text-xl leading-snug text-ink break-words">{s.suggestion}</p>
      </div>

      {!compact && s.why && (
        <div>
          <Label>Why</Label>
          <p className="text-sm text-ink/90 leading-relaxed break-words">{s.why}</p>
        </div>
      )}

      {!compact && s.evidence.length > 0 && (
        <div>
          <Label>Evidence</Label>
          <ul className="pl-4 space-y-0.5 text-xs text-muted list-disc marker:text-line-strong break-words">
            {s.evidence.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {actions.map((a) => {
          const m = ADVICE_ACTION_META[a];
          return (
            <ActionButton
              key={a}
              icon={m.icon}
              label={m.label}
              tone={m.tone}
              active={s.action === a}
              onClick={() => onReact(s, a)}
            />
          );
        })}
        {s.action && (
          <span className="text-xs text-muted sm:ml-auto">
            {ADVICE_ACTION_META[s.action].done}
            {s.acted_at && (
              <>
                , <span className="num">{timeAgo(s.acted_at, now)}</span>
              </>
            )}
          </span>
        )}
      </div>
    </article>
  );
}
