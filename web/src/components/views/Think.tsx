"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowUp, MessagesSquare, Plus, RotateCcw, TriangleAlert, X } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { Fold } from "@/components/ask/parts";
import { ErrorBanner, NoVault } from "@/components/EmptyState";
import { Bone } from "@/components/Skeleton";
import { MyTurn, ProxenosTurn, Waiting } from "@/components/think/Turn";
import { useThink } from "@/lib/client";
import { formatDateTime, timeAgo } from "@/lib/format";
import { scrollBehavior } from "@/lib/reading";
import {
  THINK_MAX_TEXT,
  type ThinkContext,
  type ThinkKind,
  type ThinkStart,
  type ThinkStep,
  type ThinkSummary,
  type ThinkThread,
} from "@/lib/types";
import { cn } from "@/lib/utils";

/** What a thread started from, as the list says it. */
const FROM: Record<ThinkKind, string> = {
  draft: "From a draft",
  project: "From a project",
  day: "From a day",
  person: "About someone",
  free: "From a note",
};

/** What a thread started from, as its top says it: "Draft: Reply to Ana". */
function startedFrom(c: ThinkContext): string {
  const kind: Record<ThinkKind, string> = { draft: "Draft", project: "Project", day: "Day", person: "About", free: "" };
  return kind[c.kind] ? `${kind[c.kind]}: ${c.title}` : c.title;
}

// What was being written when the view was left, and what was last sent, to give back if it never
// reached its thread (a model that wasn't set up, a draft that was gone), so it needn't be written again.
let kept = "";
let lastSent = "";

/** Where a message is written. ⌘↵ sends it. */
function Composer({
  text,
  onText,
  sending,
  onSend,
  placeholder,
}: {
  text: string;
  onText: (t: string) => void;
  sending: boolean;
  onSend: () => void;
  placeholder: string;
}) {
  const area = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    // Ready to type on a computer; on a phone, the keyboard waits until it's asked for.
    if (window.matchMedia("(pointer: fine)").matches) area.current?.focus({ preventScroll: true });
  }, []);
  const over = text.length - THINK_MAX_TEXT;
  const canSend = text.trim() !== "" && over <= 0 && !sending;
  return (
    <section aria-label="Your message" className="card p-3 sm:p-4">
      <label htmlFor="think-text" className="sr-only">
        Your message
      </label>
      <textarea
        id="think-text"
        ref={area}
        value={text}
        onChange={(e) => onText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && canSend) {
            e.preventDefault();
            onSend();
          }
        }}
        rows={Math.min(12, Math.max(3, text.split("\n").length + 1))}
        spellCheck
        placeholder={placeholder}
        className="w-full resize-y rounded-xl border border-line-strong bg-bg p-3 font-sans text-base leading-relaxed text-ink sm:text-[0.9375rem]"
      />
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
        <p className="min-w-0 text-xs text-muted">
          {over > 0 ? (
            <span className="num text-bad-ink">{over.toLocaleString("en-US")} characters too many</span>
          ) : (
            "From your goals, your notes and your records. It never decides for you."
          )}
        </p>
        <div className="ml-auto flex items-center gap-3">
          <span className="hidden text-xs text-muted sm:inline">⌘↵ sends</span>
          <ActionButton icon={ArrowUp} label={sending ? "Sending" : "Think"} tone="accent" active={canSend} disabled={!canSend} onClick={onSend} />
        </div>
      </div>
    </section>
  );
}

function ThreadRow({ t, now, open, onOpen }: { t: ThinkSummary; now: string; open: boolean; onOpen: () => void }) {
  return (
    <li>
      <button
        onClick={onOpen}
        aria-current={open ? "true" : undefined}
        className={cn(
          "w-full rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-surface-2",
          open && "bg-surface-2 ring-1 ring-line-strong",
        )}
      >
        <span className="block truncate text-sm font-medium text-ink">{t.title || "A thought"}</span>
        <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted">
          <span className="num" title={formatDateTime(t.updated)}>
            {timeAgo(t.updated, now)}
          </span>
          {t.kind && <span>{FROM[t.kind]}</span>}
          {t.status === "working" && <span className="text-accent">thinking</span>}
          {t.status === "failed" && <span className="text-bad-ink">no answer</span>}
        </span>
        {t.last && <span className="mt-1 line-clamp-2 block text-xs leading-relaxed text-faint">{t.last}</span>}
      </button>
    </li>
  );
}

/** What a thread started from, at its top: what it is, and what it says, folded. */
function StartedFrom({ label, text, onDrop }: { label: string; text: string | null; onDrop?: () => void }) {
  return (
    <div className="rounded-xl border border-line bg-surface-2/60 px-3.5 py-3 text-sm">
      <div className="flex items-start gap-2">
        <p className="min-w-0 flex-1 break-words">
          <span className="smallcaps mr-2 text-faint">Started from</span>
          <span className="text-ink/90">{label}</span>
        </p>
        {onDrop && (
          <button onClick={onDrop} aria-label="Start from nothing" className="-m-1 rounded-full p-1 text-muted hover:text-ink">
            <X size={14} />
          </button>
        )}
      </div>
      {text && (
        <div className="mt-2">
          <Fold label="What it says">
            <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-muted">{text}</p>
          </Fold>
        </div>
      )}
    </div>
  );
}

interface ThinkProps {
  /** A new thread another view asked for, with what it starts from (null: from nothing). */
  intent: { start: ThinkStart | null } | null;
  onConsumed: () => void;
  /** Open Ask with a message to draft. */
  onAsk: (text: string) => void;
  onMemory: (query: string, id?: string) => void;
}

/**
 * Think anything through with Proxenos, over as many turns as it takes: a decision, a message, a
 * project, a day, a thought. Each answer comes from your own goals, notes and records, with what
 * matters here, questions to sit with and what could come next, and never decides for you.
 */
export function Think({ intent, onConsumed, onAsk, onMemory }: ThinkProps) {
  const [text, setText] = useState(intent ? (intent.start?.text ?? "") : kept);
  const [start, setStart] = useState<ThinkStart | null>(intent?.start ?? null);
  const [sending, setSending] = useState(false);
  // On a phone the list and a thread take turns; on a computer they sit side by side.
  const [reading, setReading] = useState(intent !== null);
  const { data, open, select, error, clearError, pending, stopping, send, again, stop } = useThink((reached) => {
    if (reached) lastSent = "";
    else setText((t) => (t === "" ? lastSent : t));
  });
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (intent) onConsumed();
  }, [intent, onConsumed]);

  useEffect(() => {
    kept = text;
  }, [text]);

  // Bring what was just sent, and then the answer, into view.
  const thinking = pending !== null;
  const answered = data?.thread?.messages.length ?? 0;
  useEffect(() => {
    if (!thinking && answered === 0) return;
    end.current?.scrollIntoView({ behavior: scrollBehavior(), block: "end" });
  }, [thinking, answered]);

  if (data && !data.vault.exists) return <NoVault path={data.vault.path} />;

  const thread: ThinkThread | null = open && data?.thread?.id === open ? data.thread : null;
  const mine = pending !== null && pending.thread === open;
  const busy = pending !== null;

  const openThread = (id: string | null) => {
    select(id);
    if (id) setStart(null);
    setReading(true);
  };

  const submit = async () => {
    setSending(true);
    const said = text.trim();
    const ok = await send(said, open, open ? null : start);
    setSending(false);
    if (ok) {
      lastSent = said;
      setText("");
      if (!open) setStart(null);
    }
  };

  /** A step that's a message, drafted in Ask, with what the thread is about. */
  const draft = (s: ThinkStep) => {
    const first = thread?.messages.find((m) => m.role === "me")?.text ?? "";
    const about = first ? `\n\nWhat I've been thinking through: ${first.slice(0, 600)}` : "";
    onAsk(`Draft a message to ${s.draftTo}: ${s.text}${about}`);
  };

  const threads = data?.threads ?? [];
  const list = (
    <aside
      aria-label="Threads"
      className={cn(
        "w-full min-w-0 border-line p-3 md:block md:w-72 md:flex-shrink-0 md:border-r md:min-h-[calc(100dvh-7.25rem)] lg:w-80",
        reading ? "hidden" : "block",
      )}
    >
      <button
        onClick={() => openThread(null)}
        className="mb-3 inline-flex w-full items-center justify-center gap-1.5 rounded-full border border-accent/40 bg-accent/10 px-3 py-2 text-sm text-accent transition-colors hover:bg-accent/15"
      >
        <Plus size={15} />
        Think something through
      </button>
      {data === null ? (
        <div className="space-y-3 p-2" aria-hidden="true">
          <Bone className="h-4 w-3/4" />
          <Bone className="h-4 w-1/2" />
          <Bone className="h-4 w-2/3" />
        </div>
      ) : threads.length === 0 ? (
        <p className="px-2 text-sm leading-relaxed text-muted">No threads yet.</p>
      ) : (
        <ul className="space-y-1">
          {threads.map((t) => (
            <ThreadRow key={t.id} t={t} now={data.now} open={t.id === open} onOpen={() => openThread(t.id)} />
          ))}
        </ul>
      )}
    </aside>
  );

  const loadingThread = open !== null && thread === null;
  const failed = thread?.status === "failed" && !mine;
  const last = thread?.messages[thread.messages.length - 1];

  return (
    <div className="mx-auto flex w-full max-w-6xl pb-24 md:pb-10">
      {list}

      <section aria-label={thread?.title ?? "A new thread"} className={cn("min-w-0 flex-1 p-4 sm:p-6", reading ? "block" : "hidden md:block")}>
        <div className="mx-auto max-w-3xl space-y-6">
          <button onClick={() => setReading(false)} className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink md:hidden">
            <ArrowLeft size={14} /> All threads
          </button>

          {error && <ErrorBanner message={error} onDismiss={clearError} />}

          {thread ? (
            <header className="space-y-3">
              <h2 className="title-2 break-words text-xl">{thread.title}</h2>
              {thread.context && <StartedFrom label={startedFrom(thread.context)} text={thread.context.text} />}
            </header>
          ) : loadingThread ? (
            <div className="space-y-3" aria-hidden="true">
              <Bone className="h-6 w-1/2" />
              <Bone className="h-4 w-full" />
              <Bone className="h-4 w-4/5" />
            </div>
          ) : (
            <header className="space-y-3">
              <h2 className="title-2 text-xl">Think something through</h2>
              {start ? (
                <StartedFrom label={start.label} text={null} onDrop={() => setStart(null)} />
              ) : (
                !busy && (
                  <p className="max-w-2xl text-sm leading-relaxed text-muted">
                    A decision, a message to send for yourself or someone else, a project, a day, or a thought you want to turn over.
                    Proxenos answers from your own goals and values, what you&apos;ve told it, your last few days and what your memory
                    holds, with what matters here, questions to sit with and what could come next. It lays out the trade-offs and never
                    decides for you. Nothing is sent for you.
                  </p>
                )
              )}
            </header>
          )}

          {thread && (
            <div className="space-y-6">
              {thread.messages.map((m, i) =>
                m.role === "me" ? (
                  <MyTurn key={`${i}-${m.at}`} text={m.text} at={m.at} now={data?.now ?? m.at} />
                ) : (
                  <ProxenosTurn key={`${i}-${m.at}`} message={m} now={data?.now ?? m.at} onMemory={onMemory} onDraft={busy ? null : draft} />
                ),
              )}
            </div>
          )}

          {mine && pending.text && (thread === null || last?.role !== "me" || last.text !== pending.text) && (
            <MyTurn text={pending.text} at="" now="" />
          )}

          {mine && <Waiting since={pending.since} stopping={stopping} onStop={stop} />}

          {failed && thread && (
            <div className="flex flex-wrap items-start gap-3 rounded-xl border border-bad-line bg-bad-bg p-3 text-sm text-bad-ink">
              <TriangleAlert size={16} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
              <span className="min-w-0 flex-1 break-words">{thread.error ?? "It didn't finish."}</span>
              {last?.role === "me" && <ActionButton icon={RotateCcw} label="Try again" tone="neutral" disabled={busy} onClick={() => void again(thread.id)} />}
            </div>
          )}

          <div ref={end} />

          {!mine && !loadingThread && (
            <>
              {busy && (
                <p className="flex items-center gap-2 text-sm text-muted">
                  <MessagesSquare size={14} aria-hidden="true" />
                  Proxenos is thinking another thread through; this one can go on once it&apos;s done.
                </p>
              )}
              <Composer
                text={text}
                onText={setText}
                sending={sending || busy}
                onSend={() => void submit()}
                placeholder={thread ? "Say more, or answer a question…" : "What's on your mind?"}
              />
            </>
          )}
        </div>
      </section>
    </div>
  );
}
