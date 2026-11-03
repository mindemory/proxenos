import { ArrowUpRight, CalendarClock, Check, Hash, PenLine, Play, Route, Search, ThumbsDown, ThumbsUp, type LucideIcon } from "lucide-react";

import { ActionButton, type ActionTone } from "@/components/ActionButton";
import { daysBetween, localDay, plural, shortDate, timeAgo } from "@/lib/format";
import type { ChoiceAction, ChoiceEvidence, Skip, TakeOn } from "@/lib/types";
import { cn } from "@/lib/utils";

const KINDS: Record<string, string> = {
  job: "Job",
  cfp: "Call for papers",
  grant: "Grant",
  fellowship: "Fellowship",
  talk: "Talk",
  collaboration: "Collaboration",
  writing: "Writing",
  event: "Event",
  program: "Program",
  meeting: "Meeting",
  invitation: "Invitation",
  thread: "Thread",
  task: "Task",
  list: "Mailing list",
  channel: "Channel",
  commitment: "Commitment",
  other: "Other",
};

type Side = "take_on" | "skip";

/** The three actions, worded for each side: doing a skip means letting it go. */
const ACTIONS: Record<Side, Record<ChoiceAction, { label: string; icon: LucideIcon; tone: ActionTone; done: string }>> = {
  take_on: {
    useful: { label: "Useful", icon: ThumbsUp, tone: "ok", done: "You marked this useful" },
    not_me: { label: "Not me", icon: ThumbsDown, tone: "bad", done: "You said this isn't you" },
    doing: { label: "Doing it", icon: Play, tone: "accent", done: "You're taking this on" },
  },
  skip: {
    useful: { label: "Useful", icon: ThumbsUp, tone: "ok", done: "You marked this useful" },
    not_me: { label: "Not me", icon: ThumbsDown, tone: "bad", done: "You're keeping this" },
    doing: { label: "Letting it go", icon: Check, tone: "accent", done: "You're letting this go" },
  },
};

interface ChoiceCardProps {
  side: Side;
  c: TakeOn | Skip;
  now: string;
  onReact: (c: TakeOn | Skip, action: ChoiceAction) => void;
  onDraft?: (id: string) => void;
  onErrand?: (goal: string) => void;
  onMemory?: (query: string, id?: string) => void;
  flash?: boolean;
}

function Label({ children }: { children: React.ReactNode }) {
  return <div className="eyebrow mb-1">{children}</div>;
}

function Chip({ icon: Icon, tone = "plain", children }: { icon?: LucideIcon; tone?: "plain" | "warn"; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex min-w-0 items-center gap-1 rounded-md px-2 py-0.5 text-xs",
        tone === "warn" ? "border border-warn-line bg-warn-bg text-warn-ink" : "bg-surface-2 text-ink/85",
      )}
    >
      {Icon && <Icon size={12} className="flex-shrink-0" />}
      <span className="truncate">{children}</span>
    </span>
  );
}

/** When it's due, said plainly, and whether that's soon. */
function due(deadline: string, now: string): { text: string; soon: boolean } {
  const days = daysBetween(localDay(now), deadline);
  const when = days === 0 ? "today" : days === 1 ? "tomorrow" : days > 1 ? `in ${plural(days, "day")}` : "passed";
  return { text: `Due ${shortDate(`${deadline}T12:00:00`, now)}, ${when}`, soon: days <= 7 };
}

function Evidence({ items, onMemory }: { items: ChoiceEvidence[]; onMemory?: (query: string, id?: string) => void }) {
  return (
    <ul className="space-y-1 text-xs text-muted">
      {items.map((e, i) => (
        <li key={i} className="flex items-start gap-1.5 break-words">
          <span className="mt-1.5 h-1 w-1 flex-shrink-0 rounded-full bg-line-strong" aria-hidden="true" />
          {e.id && onMemory ? (
            <button
              onClick={() => onMemory(e.label, e.id)}
              className="inline-flex min-w-0 items-start gap-1 text-left hover:text-ink"
              title="Open it in Memory"
            >
              <span>{e.label}</span>
              <Search size={11} className="mt-0.5 flex-shrink-0" />
            </button>
          ) : (
            <span>{e.label}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

/** The draft the work clone writes for a choice: open it once written, else say when it will be. */
function DraftLink({ draft, onDraft }: { draft: TakeOn["draft"]; onDraft?: (id: string) => void }) {
  if (!draft) return null;
  if (!draft.status) return <span className="text-xs text-muted">Its draft is written tonight, in Drafts.</span>;
  return (
    <ActionButton
      icon={PenLine}
      label={draft.status === "draft" ? "Open the draft" : `Draft ${draft.status}`}
      tone="accent"
      onClick={() => onDraft?.(draft.id)}
    />
  );
}

/** One thing worth taking on, or worth skipping: what, why, the evidence, a step ready to go, and the three actions. */
export function ChoiceCard({ side, c, now, onReact, onDraft, onErrand, onMemory, flash = false }: ChoiceCardProps) {
  const takeOn = side === "take_on" ? (c as TakeOn) : null;
  const skip = side === "skip" ? (c as Skip) : null;
  const deadline = takeOn?.deadline ? due(takeOn.deadline, now) : null;
  const step = takeOn?.step.what ? takeOn.step : null;
  const actions = ACTIONS[side];

  return (
    <article
      className={cn(
        "card space-y-4 p-4 transition-opacity sm:p-5",
        flash && "row-flash",
        c.action === "not_me" && "opacity-60 hover:opacity-90",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Chip icon={Hash}>{KINDS[c.kind] ?? c.kind}</Chip>
        {deadline && (
          <Chip icon={CalendarClock} tone={deadline.soon ? "warn" : "plain"}>
            {deadline.text}
          </Chip>
        )}
        {skip?.cost && <Chip>{skip.cost}</Chip>}
      </div>

      <h3 className="break-words font-display text-xl leading-snug text-ink">{c.title}</h3>

      {c.why && <p className="break-words text-sm leading-relaxed text-ink/90">{c.why}</p>}

      {step && (
        <div className="space-y-3 rounded-xl border border-accent/25 bg-accent/[0.06] p-4">
          <div>
            <div className="smallcaps mb-1.5 text-accent">{step.kind === "errand" ? "First step, as an errand" : "First step"}</div>
            <p className="break-words text-[0.9375rem] leading-relaxed text-ink">{step.what}</p>
            {step.to && <p className="mt-1 text-xs text-muted">To {step.to}</p>}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {step.kind === "errand" ? (
              <ActionButton icon={Route} label="Start the errand" tone="accent" onClick={() => onErrand?.(step.what)} />
            ) : (
              <DraftLink draft={c.draft} onDraft={onDraft} />
            )}
            {takeOn?.link && (
              <a
                href={takeOn.link}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-[0.8125rem] text-muted hover:text-ink"
              >
                Open the page <ArrowUpRight size={13} />
              </a>
            )}
          </div>
        </div>
      )}

      {skip?.decline && (
        <div className="space-y-3 rounded-xl border border-line-strong bg-surface-2/60 p-4">
          <div>
            <div className="smallcaps mb-1.5">An answer to send</div>
            <p className="break-words text-[0.9375rem] leading-relaxed text-ink">{skip.decline.what}</p>
            {skip.decline.to && <p className="mt-1 text-xs text-muted">To {skip.decline.to}</p>}
          </div>
          <DraftLink draft={c.draft} onDraft={onDraft} />
        </div>
      )}

      {c.evidence.length > 0 && (
        <div>
          <Label>From your records</Label>
          <Evidence items={c.evidence} onMemory={onMemory} />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {(Object.keys(actions) as ChoiceAction[]).map((a) => (
          <ActionButton
            key={a}
            icon={actions[a].icon}
            label={actions[a].label}
            tone={actions[a].tone}
            active={c.action === a}
            onClick={() => onReact(c, a)}
          />
        ))}
        {c.action && (
          <span className="text-xs text-muted sm:ml-auto">
            {actions[c.action].done}
            {c.acted_at && (
              <>
                , <span className="num">{timeAgo(c.acted_at, now)}</span>
              </>
            )}
          </span>
        )}
      </div>
    </article>
  );
}
