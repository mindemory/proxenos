"use client";

import { LoaderCircle, PenLine, X } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { Elapsed } from "@/components/ask/Thinking";
import { Markdown } from "@/components/Markdown";
import { formatDateTime, timeAgo } from "@/lib/format";
import type { ThinkMatter, ThinkMessage, ThinkStep } from "@/lib/types";

/** What the reader wrote: their words as written, set to the right. */
export function MyTurn({ text, at, now }: { text: string; at: string; now: string }) {
  return (
    <div className="ml-auto flex max-w-[88%] flex-col items-end gap-1">
      <div className="rounded-2xl rounded-br-md border border-line-strong bg-surface-2 px-4 py-2.5">
        <p className="whitespace-pre-wrap break-words leading-relaxed text-ink">{text}</p>
      </div>
      {at && (
        <span className="text-xs text-faint" title={formatDateTime(at)}>
          You · <span className="num">{timeAgo(at, now)}</span>
        </span>
      )}
    </div>
  );
}

/** A quiet section under a reply: a small-caps label and its lines. */
function Part({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section aria-label={label} className="space-y-1.5">
      <h4 className="smallcaps text-faint">{label}</h4>
      <ul className="space-y-1.5 text-sm leading-relaxed text-ink/85">{children}</ul>
    </section>
  );
}

function Matter({ m, onMemory }: { m: ThinkMatter; onMemory: (query: string, id?: string) => void }) {
  return (
    <li className="break-words">
      {m.text}{" "}
      {m.label &&
        (m.record ? (
          <button
            onClick={() => onMemory("", m.record)}
            className="text-xs text-muted underline decoration-line-strong underline-offset-4 hover:text-accent hover:decoration-accent"
          >
            {m.label}
          </button>
        ) : (
          <span className="text-xs text-muted">{m.label}</span>
        ))}
    </li>
  );
}

function Step({ s, onDraft }: { s: ThinkStep; onDraft: ((s: ThinkStep) => void) | null }) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1.5 break-words">
      <span className="min-w-0">{s.text}</span>
      {s.draftTo && onDraft && <ActionButton icon={PenLine} label="Draft this" tone="neutral" onClick={() => onDraft(s)} />}
    </li>
  );
}

interface ProxenosTurnProps {
  message: ThinkMessage;
  now: string;
  onMemory: (query: string, id?: string) => void;
  /** Draft a step that's a message; null while one can't be. */
  onDraft: ((s: ThinkStep) => void) | null;
}

/** Proxenos's answer: the reply, then, quietly, what matters here, questions to sit with and what could come next. */
export function ProxenosTurn({ message: m, now, onMemory, onDraft }: ProxenosTurnProps) {
  return (
    <article className="min-w-0 space-y-4">
      <p className="flex items-baseline gap-2">
        <span className="smallcaps text-accent">Proxenos</span>
        {m.at && (
          <span className="text-xs text-faint" title={formatDateTime(m.at)}>
            <span className="num">{timeAgo(m.at, now)}</span>
          </span>
        )}
      </p>
      <Markdown source={m.text} />
      {(m.matters.length > 0 || m.questions.length > 0 || m.next.length > 0) && (
        <div className="space-y-4 border-l-2 border-line-strong pl-3.5">
          {m.matters.length > 0 && (
            <Part label="What matters here">
              {m.matters.map((x) => (
                <Matter key={x.text} m={x} onMemory={onMemory} />
              ))}
            </Part>
          )}
          {m.questions.length > 0 && (
            <Part label="Questions to sit with">
              {m.questions.map((q) => (
                <li key={q} className="break-words">
                  {q}
                </li>
              ))}
            </Part>
          )}
          {m.next.length > 0 && (
            <Part label="Next, if you like">
              {m.next.map((s) => (
                <Step key={s.text} s={s} onDraft={onDraft} />
              ))}
            </Part>
          )}
        </div>
      )}
    </article>
  );
}

interface WaitingProps {
  /** When it began, in ms since 1970. */
  since: number;
  stopping: boolean;
  onStop: () => void;
}

/** What shows while Proxenos thinks: it can take minutes on a local model, so say so, calmly. */
export function Waiting({ since, stopping, onStop }: WaitingProps) {
  return (
    <section className="card flex flex-col gap-3 p-4 sm:p-5" role="status" aria-live="polite" aria-label="Thinking it over">
      <div className="flex items-start gap-3">
        <div className="rounded-full bg-accent/10 p-2.5 text-accent">
          <LoaderCircle size={17} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1 space-y-1">
          <p className="flex flex-wrap items-baseline gap-x-2.5">
            <span className="title-2">Thinking it over</span>
            {/* Ticking every second: kept out of the live region, or a screen reader would read it out each time. */}
            <span className="text-sm text-muted" aria-hidden="true">
              <Elapsed since={since} />
            </span>
          </p>
          <p className="leading-relaxed text-muted">
            Proxenos reads your goals, what you&apos;ve told it and what your memory holds on this, then answers. On your Mac&apos;s
            model that can take a few minutes. You can leave this page: the answer will be here when you come back.
          </p>
        </div>
      </div>
      <div>
        <ActionButton icon={X} label={stopping ? "Stopping" : "Stop"} tone="bad" disabled={stopping} onClick={onStop} />
      </div>
    </section>
  );
}
