import { Check, ChevronRight, UserX, X, type LucideIcon } from "lucide-react";

import { ActionButton, type ActionTone } from "@/components/ActionButton";
import { SourceBadge } from "@/components/SourceBadge";
import { shortDate } from "@/lib/format";
import { dueLabel, placeOf, type Tone } from "@/lib/tasks";
import type { TaskAction, TaskPriority, TaskView } from "@/lib/types";
import { cn } from "@/lib/utils";

// Priority stays off the status hues so it never reads as "overdue".
const PRIORITY_STYLE: Record<TaskPriority, string> = {
  high: "border-accent/40 bg-accent/10 text-accent",
  medium: "border-line-strong bg-surface-2 text-ink/85",
  low: "border-line text-muted",
};

const TONE_TEXT: Record<Tone, string> = {
  bad: "text-bad-ink",
  warn: "text-warn-ink",
  ok: "text-ok-ink",
  muted: "text-muted",
};

export const TASK_ACTION_META: Record<TaskAction, { label: string; icon: LucideIcon; tone: ActionTone }> = {
  done: { label: "Done", icon: Check, tone: "ok" },
  not_mine: { label: "Not mine", icon: UserX, tone: "neutral" },
  dismiss: { label: "Dismiss", icon: X, tone: "neutral" },
};

interface TaskRowProps {
  task: TaskView;
  now: string;
  actions?: readonly TaskAction[];
  onAct?: (task: TaskView, action: TaskAction) => void;
  showEvidence?: boolean;
  flash?: boolean;
}

export function TaskRow({ task: t, now, actions = [], onAct, showEvidence = true, flash = false }: TaskRowProps) {
  const due = dueLabel(t, now);
  const done = placeOf(t) === "done";

  return (
    <li className={cn("px-4 sm:px-6 py-4", flash && "row-flash")}>
      <div className="flex items-start justify-between gap-3">
        <h3 className={cn("font-medium leading-snug break-words min-w-0", done ? "text-muted" : "text-ink")}>{t.title}</h3>
        <span
          className={cn(
            "text-[10.5px] uppercase tracking-wider px-1.5 py-0.5 rounded-md border whitespace-nowrap flex-shrink-0",
            PRIORITY_STYLE[t.priority],
          )}
          title={`${t.priority} priority`}
        >
          {t.priority}
        </span>
      </div>

      {t.detail && <p className="text-sm text-muted leading-relaxed line-clamp-2 mt-1 break-words">{t.detail}</p>}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted">
        <SourceBadge kind={t.source} />
        {t.with && (
          <span className="min-w-0 break-words">
            with <span className="text-ink/90">{t.with}</span>
          </span>
        )}
        {t.asked_at && shortDate(t.asked_at, now) && (
          <span>
            asked <span className="num">{shortDate(t.asked_at, now)}</span>
          </span>
        )}
        {due && (
          <span className={cn("num", TONE_TEXT[due.tone])} title={due.title || undefined}>
            {due.text}
          </span>
        )}
      </div>

      {showEvidence && t.evidence.length > 0 && (
        <details className="mt-2 group">
          <summary className="list-none [&::-webkit-details-marker]:hidden inline-flex items-center gap-1 text-xs text-muted cursor-pointer select-none hover:text-ink rounded">
            <ChevronRight size={12} className="transition-transform group-open:rotate-90" />
            Evidence <span className="num">({t.evidence.length})</span>
          </summary>
          <ul className="mt-1.5 pl-4 space-y-1 text-xs text-muted list-disc marker:text-line-strong break-words">
            {t.evidence.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </details>
      )}

      {onAct && actions.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {actions.map((a) => {
            const m = TASK_ACTION_META[a];
            return <ActionButton key={a} icon={m.icon} label={m.label} tone={m.tone} onClick={() => onAct(t, a)} />;
          })}
        </div>
      )}
    </li>
  );
}
