"use client";

import { useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import {
  Activity,
  Check,
  ChevronRight,
  CircleSlash,
  ClipboardCheck,
  ClipboardList,
  Copy,
  FlaskConical,
  FolderOpen,
  Forward,
  Hourglass,
  Mail,
  MessageSquare,
  MessageSquareText,
  Phone,
  Pill,
  Printer,
  Receipt,
  ShieldCheck,
  Stethoscope,
  type LucideIcon,
} from "lucide-react";

import { ActionButton, type ActionTone } from "@/components/ActionButton";
import { Markdown } from "@/components/Markdown";
import { SourceIcon, sourceMeta } from "@/components/SourceBadge";
import { useToast } from "@/components/Toasts";
import { careDue, careStatus, copyText } from "@/lib/careClient";
import { formatDate, localDay, shortDate } from "@/lib/format";
import type {
  CareAction,
  CareCited,
  CareEvent,
  CareEventKind,
  CareItemKind,
  CareItemView,
  CareScript,
  CareScriptKind,
} from "@/lib/types";
import { cn } from "@/lib/utils";

/** Open a record's conversation in Memory. */
export type OpenRecord = (query: string, id?: string) => void;

const EVENT_META: Record<CareEventKind, { label: string; icon: LucideIcon }> = {
  symptom: { label: "Symptom", icon: Activity },
  visit: { label: "Visit", icon: Stethoscope },
  test: { label: "Test", icon: FlaskConical },
  result: { label: "Result", icon: ClipboardCheck },
  referral: { label: "Referral", icon: Forward },
  call: { label: "Call", icon: Phone },
  message: { label: "Message", icon: MessageSquare },
  bill: { label: "Bill", icon: Receipt },
  claim: { label: "Claim", icon: ShieldCheck },
  records: { label: "Records", icon: FolderOpen },
  prescription: { label: "Prescription", icon: Pill },
};

export const ITEM_KIND_LABEL: Record<CareItemKind, string> = {
  appointment: "Appointment",
  referral: "Referral",
  bill: "Bill",
  claim: "Claim",
  records: "Records",
  prescription: "Prescription",
  form: "Form",
  follow_up: "Follow-up",
  question: "Question",
};

const SCRIPT_META: Record<CareScriptKind, { label: string; icon: LucideIcon }> = {
  call: { label: "Call", icon: Phone },
  email: { label: "Email", icon: Mail },
  portal_message: { label: "Portal message", icon: MessageSquareText },
  form: { label: "Form", icon: ClipboardList },
};

export const CARE_ACTION_META: Record<CareAction, { label: string; icon: LucideIcon; tone: ActionTone }> = {
  done: { label: "Done", icon: Check, tone: "ok" },
  waiting: { label: "Waiting", icon: Hourglass, tone: "warn" },
  not_relevant: { label: "Not relevant", icon: CircleSlash, tone: "neutral" },
};

const TONE_TEXT = { bad: "text-bad-ink", warn: "text-warn-ink", muted: "text-muted" } as const;

const PILL = "inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px] leading-4";

/** The section label the views use: an eyebrow, a hint, and a count. */
export function SectionHeader({ title, count, hint }: { title: string; count?: number; hint?: string }) {
  return (
    <div className="flex justify-between gap-3 border-b border-line bg-surface/60 px-4 py-2 sm:px-6">
      <span className="eyebrow">
        {title}
        {hint && <span className="normal-case tracking-normal"> · {hint}</span>}
      </span>
      {count !== undefined && <span className="num text-xs text-muted">{count}</span>}
    </div>
  );
}

/** The records an entry rests on, by source and date. Each opens its conversation in Memory. */
export function Evidence({
  ids,
  cited,
  now,
  onOpen,
}: {
  ids: string[];
  cited: Record<string, CareCited>;
  now: string;
  onOpen?: OpenRecord;
}) {
  const known = ids.filter((id) => cited[id]);
  if (known.length === 0) return null;
  return (
    <details className="group mt-2">
      <summary className="inline-flex cursor-pointer select-none list-none items-center gap-1 rounded text-xs text-muted hover:text-ink [&::-webkit-details-marker]:hidden">
        <ChevronRight size={12} className="transition-transform group-open:rotate-90" />
        From your records <span className="num">({known.length})</span>
      </summary>
      <ul className="mt-1.5 flex flex-wrap gap-1.5 pl-4">
        {known.map((id) => {
          const c = cited[id];
          const label = `${sourceMeta(c.source).label}, ${shortDate(c.ts, now)}`;
          return (
            <li key={id}>
              <button
                type="button"
                onClick={() => onOpen?.("", id)}
                disabled={!onOpen}
                title={onOpen ? "Open in Memory" : undefined}
                className="inline-flex items-center gap-1.5 rounded-md border border-line px-1.5 py-0.5 text-xs text-muted transition-colors enabled:hover:border-line-strong enabled:hover:text-ink"
              >
                <SourceIcon kind={c.source} />
                {label}
              </button>
            </li>
          );
        })}
      </ul>
    </details>
  );
}

/** One open item: what it is, the next step, when it's due, and the reader's three marks. */
export function CareItemRow({
  item: i,
  now,
  cited,
  scripts = 0,
  flash = false,
  focused = false,
  onAct,
  onOpen,
}: {
  item: CareItemView;
  now: string;
  cited: Record<string, CareCited>;
  scripts?: number;
  flash?: boolean;
  /** Opened from the home page: marked so the eye lands on it. */
  focused?: boolean;
  onAct?: (item: CareItemView, action: CareAction) => void;
  onOpen?: OpenRecord;
}) {
  const place = careStatus(i);
  const due = careDue(i, now);
  return (
    <li id={`care-${i.id}`} className={cn("scroll-mt-20 px-4 py-4 sm:px-6", (flash || focused) && "row-flash")}>
      <div className="flex items-start justify-between gap-3">
        <h3 className={cn("min-w-0 break-words font-medium leading-snug", place === "done" ? "text-muted" : "text-ink")}>{i.title}</h3>
        <span className={cn(PILL, "flex-shrink-0 border-line-strong bg-surface-2 text-ink/85")}>{ITEM_KIND_LABEL[i.kind]}</span>
      </div>
      {i.next_step && place !== "done" && (
        <p className="mt-1 break-words text-sm leading-relaxed text-muted">
          <span className="text-ink/90">Next:</span> {i.next_step}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted">
        {due && <span className={cn("num", TONE_TEXT[due.tone])}>{due.text}</span>}
        {place === "waiting" && (
          <span className="inline-flex items-center gap-1">
            <Hourglass size={12} aria-hidden="true" />
            {i.action === "waiting" ? "You marked it waiting" : "Waiting"}
          </span>
        )}
        {place === "done" && (
          <span className="inline-flex items-center gap-1 text-ok-ink">
            <Check size={12} aria-hidden="true" />
            Done
          </span>
        )}
        {scripts > 0 && <span>{scripts === 1 ? "A script below" : `${scripts} scripts below`}</span>}
      </div>
      <Evidence ids={i.evidence} cited={cited} now={now} onOpen={onOpen} />
      {onAct && (
        <div className="mt-3 flex flex-wrap gap-2">
          {(Object.keys(CARE_ACTION_META) as CareAction[]).map((a) => {
            const m = CARE_ACTION_META[a];
            return <ActionButton key={a} icon={m.icon} label={m.label} tone={m.tone} active={i.action === a} onClick={() => onAct(i, a)} />;
          })}
        </div>
      )}
    </li>
  );
}

/** The story so far, oldest first, with a marker where today falls. */
export function Timeline({
  events,
  now,
  cited,
  onOpen,
}: {
  events: CareEvent[];
  now: string;
  cited: Record<string, CareCited>;
  onOpen?: OpenRecord;
}) {
  const today = localDay(now);
  const past = events.filter((e) => e.date <= today);
  const ahead = events.filter((e) => e.date > today);
  const row = (e: CareEvent, upcoming: boolean, last: boolean) => {
    const { label, icon: Icon } = EVENT_META[e.kind];
    return (
      <li key={e.id} className={cn("relative flex gap-3.5", !last && "pb-5")}>
        {!last && <span className="absolute bottom-0 left-[15.5px] top-9 w-px bg-line" aria-hidden="true" />}
        <span
          className={cn(
            "relative z-10 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border",
            upcoming ? "border-accent/40 bg-accent/10 text-accent" : "border-line-strong bg-surface-2 text-ink/80",
          )}
          aria-hidden="true"
        >
          <Icon size={15} />
        </span>
        <div className="min-w-0 flex-1 pt-0.5">
          <p className="flex flex-wrap items-baseline gap-x-2 text-xs text-muted">
            <span className="num text-ink/85">{formatDate(e.date)}</span>
            <span className="smallcaps text-[0.75rem]">{label}</span>
            {e.with && <span className="min-w-0 break-words">· {e.with}</span>}
          </p>
          <h4 className="title-3 mt-0.5 break-words">{e.title}</h4>
          {e.detail && <p className="mt-0.5 break-words text-sm leading-relaxed text-muted">{e.detail}</p>}
          <Evidence ids={e.evidence} cited={cited} now={now} onOpen={onOpen} />
        </div>
      </li>
    );
  };
  return (
    <div className="px-4 py-5 sm:px-6">
      <ol>{past.map((e, n) => row(e, false, n === past.length - 1))}</ol>
      {ahead.length > 0 && (
        <>
          <p className="smallcaps my-4 flex items-center gap-3 text-accent">
            Today and ahead <span className="h-px flex-1 bg-accent/25" aria-hidden="true" />
          </p>
          <ol>{ahead.map((e, n) => row(e, true, n === ahead.length - 1))}</ol>
        </>
      )}
    </div>
  );
}

/** A script with its kind, the item it's for, and a Copy button. Nothing is sent from here. */
export function ScriptCard({ script: s, itemTitle }: { script: CareScript; itemTitle?: string }) {
  const notify = useToast();
  const [copied, setCopied] = useState(false);
  const { label, icon: Icon } = SCRIPT_META[s.kind];
  const copy = () => {
    copyText(s.body).then((ok) => {
      if (!ok) return notify("Couldn't reach the clipboard. Select the text and copy it by hand.", "info");
      setCopied(true);
      notify("Copied to the clipboard", "ok");
      window.setTimeout(() => setCopied(false), 1800);
    });
  };
  return (
    <li className="card p-4 sm:p-5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className={cn(PILL, "border-accent/25 bg-accent/10 text-accent")}>
          <Icon size={12} aria-hidden="true" />
          {label}
        </span>
        {itemTitle && <span className="min-w-0 break-words text-xs text-muted">for {itemTitle}</span>}
      </div>
      {s.title && <h4 className="title-3 mt-2 break-words">{s.title}</h4>}
      <p className="mt-2 whitespace-pre-wrap break-words rounded-xl border border-line bg-bg/40 p-3.5 text-sm leading-relaxed text-ink/90">
        {s.body}
      </p>
      <div className="mt-3">
        <ActionButton icon={copied ? Check : Copy} label={copied ? "Copied" : "Copy"} tone="accent" active={copied} onClick={copy} />
      </div>
    </li>
  );
}

// ── The visit brief ─────────────────────────────────────────────────────────

const noSubscribe = () => () => {};

/** Printing shows only the brief: everything else on the page is hidden, and it prints in black on white. */
const PRINT_CSS = `
.care-print { display: none; }
@media print {
  @page { margin: 14mm 16mm; }
  html, body { background: #fff !important; }
  body > *:not(.care-print) { display: none !important; }
  .care-print { display: block !important; color: #111; font-size: 10.5pt; line-height: 1.45; }
  .care-print * { color: #111 !important; background: transparent !important; border-color: #999 !important; box-shadow: none !important; }
  .care-print h1 { font-size: 16pt; margin: 0 0 2pt; }
  .care-print h3, .care-print h4 { font-size: 11.5pt !important; margin-top: 8pt; break-after: avoid; }
  .care-print li, .care-print p { break-inside: avoid; }
  .care-print li::marker { color: #111 !important; }
  .care-print .care-print-meta { font-size: 9pt; margin-bottom: 10pt; padding-bottom: 6pt; border-bottom: 1px solid #999; }
  .care-print .care-print-fill { display: flex; gap: 24pt; margin: 4pt 0 10pt; font-size: 10pt; }
  .care-print .care-print-fill span { flex: 1; border-bottom: 1px solid #999; padding-bottom: 2pt; }
  .care-print .care-print-foot { margin-top: 12pt; font-size: 8.5pt; }
}
`;

/** The one-page brief for the next clinician: on screen in a card, and in print on its own. */
export function VisitBrief({ brief, generated }: { brief: string; generated: string | null }) {
  // The print copy goes straight into the body, so it can print without the app around it.
  const mounted = useSyncExternalStore(noSubscribe, () => true, () => false);
  const prepared = generated ? formatDate(generated) : "";

  return (
    <div className="px-4 py-5 sm:px-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="min-w-0 flex-1 text-sm leading-relaxed text-muted">
          One page for your next appointment, from your own records. Print it, or show it on your screen.
        </p>
        <button
          type="button"
          onClick={() => window.print()}
          className="inline-flex items-center gap-1.5 rounded-full bg-accent px-3.5 py-1.5 text-sm font-medium text-accent-ink transition-opacity hover:opacity-90"
        >
          <Printer size={15} aria-hidden="true" />
          Print
        </button>
      </div>
      <article className="card p-5 sm:p-7">
        <header className="mb-4 border-b border-line pb-3">
          <h2 className="title-2 text-2xl">Visit brief</h2>
          {prepared && <p className="mt-1 text-sm text-muted">Prepared {prepared}, from my own notes, messages and records.</p>}
        </header>
        <Markdown source={brief} />
      </article>
      <style>{PRINT_CSS}</style>
      {mounted &&
        createPortal(
          <div className="care-print" aria-hidden="true">
            <h1>Visit brief</h1>
            <p className="care-print-meta">
              {prepared ? `Prepared ${prepared}, ` : ""}from my own notes, messages and records. Patient-reported; not a medical record.
            </p>
            <div className="care-print-fill">
              <span>Name</span>
              <span>Date of birth</span>
            </div>
            <Markdown source={brief} compact />
          </div>,
          document.body,
        )}
    </div>
  );
}
