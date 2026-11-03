"use client";

import { useEffect, useId, useState } from "react";
import { ArrowRight, ArrowUpRight, Bookmark, BookmarkCheck, CalendarClock, Check, Copy } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { ChannelBadge } from "@/components/drafts/badges";
import { Listen } from "@/components/reading/Listen";
import { useToast } from "@/components/Toasts";
import { copyText } from "@/lib/client";
import { daysBetween, localDay, plural, shortDate } from "@/lib/format";
import type { Opening, OpeningDraft, OpeningVerdict } from "@/lib/types";
import { cn } from "@/lib/utils";

const VERDICTS: Record<OpeningVerdict, { label: string; className: string }> = {
  apply: { label: "Apply", className: "border-ok-line bg-ok-bg text-ok-ink" },
  maybe: { label: "Maybe", className: "border-warn-line bg-warn-bg text-warn-ink" },
  skip: { label: "Skip", className: "border-line-strong bg-surface-2 text-muted" },
};

const KINDS: Record<string, string> = {
  job: "Job",
  postdoc: "Postdoc",
  residency: "Residency",
  fellowship: "Fellowship",
  scholar_program: "Scholar program",
  cfp: "Call for papers",
  workshop: "Workshop",
};

const MODES: Record<string, string> = { "on-site": "On site", remote: "Remote", hybrid: "Hybrid" };

/** What the first step is, said plainly. */
function stepName(draft: OpeningDraft): string {
  if (draft.step === "message") return draft.to ? `A note to ${draft.to}` : "A note to whoever posted it";
  return draft.step === "plan" ? "A plan for the submission" : "The opening of a cover letter";
}

/** When it's due, said plainly, and whether that's soon. */
function due(deadline: string, now: string): { text: string; soon: boolean } {
  const days = daysBetween(localDay(now), deadline);
  const when = days === 0 ? "today" : days === 1 ? "tomorrow" : days > 1 ? `in ${plural(days, "day")}` : "passed";
  return { text: `Due ${shortDate(`${deadline}T12:00:00`, now)}, ${when}`, soon: days <= 7 };
}

/** An opening's first step, in the reader's voice: a few lines of it, and its actions. */
function FirstStep({ draft, title, onDrafts }: { draft: OpeningDraft; title: string; onDrafts: () => void }) {
  const notify = useToast();
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  const bodyId = useId();
  // A few lines show at first, so the list stays short; a note that fits in them shows whole.
  const long = draft.body.length > 240 || draft.body.split("\n").length > 3;
  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1600);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const copy = async () => {
    const ok = await copyText(draft.body);
    setFailed(!ok);
    if (!ok) return;
    notify("Copied to the clipboard", "ok");
    setCopied(true);
  };

  return (
    <div className="rounded-lg border border-line bg-surface-2 p-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        <span className="smallcaps">First step</span>
        <span className="min-w-0 break-words text-sm text-ink/90">{stepName(draft)}</span>
        {draft.step === "message" && <ChannelBadge channel={draft.channel} />}
      </div>
      <p id={bodyId} className={cn("mt-2 whitespace-pre-wrap break-words text-sm leading-relaxed text-ink", long && !open && "line-clamp-3")}>
        {draft.body}
      </p>
      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-2">
        {long && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-controls={bodyId}
            className="text-xs text-accent underline-offset-4 hover:underline"
          >
            {open ? "Show less" : "Show all"}
          </button>
        )}
        <ActionButton
          icon={copied ? Check : Copy}
          label={copied ? "Copied" : "Copy"}
          name={`${copied ? "Copied" : "Copy"} the first step for ${title}`}
          tone="accent"
          active={copied}
          onClick={() => void copy()}
        />
        <Listen id={`opening:${draft.id}`} text={draft.body} what={`the first step for ${title}`} />
        <button
          type="button"
          onClick={onDrafts}
          className="inline-flex items-center gap-1 text-xs text-accent underline-offset-4 hover:underline"
        >
          Also in Drafts
          <ArrowRight size={13} aria-hidden="true" />
        </button>
      </div>
      {failed && <p className="mt-2 text-xs text-bad-ink">Couldn&apos;t reach the clipboard. Select the text and copy it by hand.</p>}
    </div>
  );
}

interface OpeningRowProps {
  opening: Opening;
  now: string;
  onDrafts: () => void;
  /** Keep it for the week's choices: null once kept, else why not. */
  onKeep: () => Promise<string | null>;
}

/** One opening: the verdict, what and who, the deadline, why, its first step, and Keep. */
function OpeningRow({ opening: o, now, onDrafts, onKeep }: OpeningRowProps) {
  const [keeping, setKeeping] = useState(false);
  const [keptNow, setKeptNow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const titleId = useId();
  const kept = o.kept || keptNow;
  const verdict = VERDICTS[o.verdict];
  const deadline = o.deadline ? due(o.deadline, now) : null;
  const facts = [KINDS[o.kind] ?? o.kind, o.place, MODES[o.mode] ?? o.mode, o.pay].filter(Boolean);

  // Never disabled, so focus stays on it once it's pressed; keeping it again does nothing.
  const keep = async () => {
    if (kept || keeping) return;
    setKeeping(true);
    const why = await onKeep();
    setKeeping(false);
    setError(why);
    if (why === null) setKeptNow(true);
  };

  return (
    <article aria-labelledby={titleId} className="space-y-2.5 p-3 sm:p-4">
      <div className="flex flex-wrap items-start gap-x-2.5 gap-y-1.5">
        <span className={cn("mt-0.5 rounded-md border px-1.5 py-0.5 text-xs font-medium", verdict.className)}>{verdict.label}</span>
        <h3 id={titleId} className="min-w-0 flex-1 basis-48 break-words text-[0.9375rem] font-medium leading-snug text-ink">
          {o.title}
          {o.org && <span className="font-normal text-muted">, {o.org}</span>}
        </h3>
        {deadline && (
          <span
            className={cn(
              "inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-0.5 text-xs",
              deadline.soon ? "border border-warn-line bg-warn-bg text-warn-ink" : "bg-surface-2 text-ink/85",
            )}
          >
            <CalendarClock size={12} aria-hidden="true" />
            {deadline.text}
          </span>
        )}
      </div>
      {facts.length > 0 && <p className="break-words text-xs text-muted">{facts.join(" · ")}</p>}
      {o.why && <p className="break-words text-sm leading-relaxed text-ink/90">{o.why}</p>}
      {o.draft && <FirstStep draft={o.draft} title={o.title} onDrafts={onDrafts} />}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <ActionButton
          icon={kept ? BookmarkCheck : Bookmark}
          label={kept ? "Kept" : keeping ? "Keeping" : "Keep"}
          name={kept ? `Kept ${o.title} for this week's choices` : `Keep ${o.title} for this week's choices`}
          tone="accent"
          active={kept}
          onClick={() => void keep()}
        />
        {o.link && (
          <a
            href={o.link}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs text-accent underline-offset-4 hover:underline"
          >
            Open the post<span className="sr-only">: {o.title}, in a new tab</span>
            <ArrowUpRight size={13} aria-hidden="true" />
          </a>
        )}
      </div>
      {error && (
        <p className="text-xs text-bad-ink" role="alert">
          {error}
        </p>
      )}
    </article>
  );
}

interface OpeningsProps {
  openings: Opening[];
  now: string;
  onDrafts: () => void;
  onKeep: (opening: Opening) => Promise<string | null>;
}

/**
 * The openings in what was shared (job posts, calls, fellowships), apply first, short enough to
 * scan: each says whether to go for it, by when and why, with its first step drafted. Keep adds
 * one to the openings the week's choices weigh. Nothing is applied for or sent.
 */
export function Openings({ openings, now, onDrafts, onKeep }: OpeningsProps) {
  const headingId = useId();
  if (openings.length === 0) return null;
  return (
    <section aria-labelledby={headingId} className="space-y-2">
      <h2 id={headingId} className="smallcaps">
        {openings.length === 1 ? "One opening" : <><span className="num">{openings.length}</span> openings</>}
      </h2>
      <ol className="divide-y divide-line overflow-hidden rounded-xl border border-line-strong">
        {openings.map((o) => (
          <li key={o.id}>
            <OpeningRow opening={o} now={now} onDrafts={onDrafts} onKeep={() => onKeep(o)} />
          </li>
        ))}
      </ol>
    </section>
  );
}
