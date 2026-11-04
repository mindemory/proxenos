"use client";

import { useState } from "react";
import { Check, Phone, PhoneOff, X } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { Command, EmptyState, ErrorBanner, NoVault } from "@/components/EmptyState";
import { ProseSkeleton } from "@/components/Skeleton";
import { useCalls } from "@/lib/callsClient";
import { formatDateTime, timeAgo } from "@/lib/format";
import type { CallLine, CallPhase, CallRecord, CallSheet } from "@/lib/types";
import { cn } from "@/lib/utils";

const PHASE: Record<CallPhase, string> = {
  dialing: "Dialing",
  menu: "Pressing through the phone menu",
  waiting: "On hold. It's listening, so you don't have to",
  talking: "The assistant is talking with them",
  connecting: "Ringing you: press 1 to be put through",
  connected: "You're on the line",
  done: "Ended",
};

const WHO: Record<CallLine["who"], string> = { them: "Them", assistant: "Assistant", line: "Hold", note: "" };

function Transcript({ lines, now }: { lines: CallLine[]; now: string }) {
  if (lines.length === 0) return <p className="text-xs text-muted">Nothing said yet.</p>;
  return (
    <ol className="space-y-1.5 text-sm">
      {lines.map((l, i) => (
        <li key={`${l.at}-${i}`} className={cn("break-words", l.who === "note" || l.who === "line" ? "text-muted" : "text-ink/90")}>
          {WHO[l.who] && <span className="eyebrow mr-1.5">{WHO[l.who]}</span>}
          {l.who === "note" ? <em>{l.text}</em> : l.text}
          <span className="num ml-2 text-[0.6875rem] text-muted" title={formatDateTime(l.at)}>
            {timeAgo(l.at, now)}
          </span>
        </li>
      ))}
    </ol>
  );
}

function Asks({ sheet, done }: { sheet: CallSheet; done: number[] }) {
  if (sheet.asks.length === 0) return null;
  return (
    <ol className="space-y-1 text-sm text-ink/90">
      {sheet.asks.map((a, i) => (
        <li key={a} className="flex items-start gap-2">
          <span className={cn("num mt-0.5 w-4 shrink-0 text-xs", done.includes(i + 1) ? "text-ok-ink" : "text-muted")}>
            {done.includes(i + 1) ? <Check size={13} /> : `${i + 1}.`}
          </span>
          <span className="break-words">{a}</span>
        </li>
      ))}
    </ol>
  );
}

function Notes({ r }: { r: CallRecord }) {
  const o = r.outcome;
  const reference = o?.reference || r.notes.reference;
  const who = o?.rep_name || r.notes.rep_name;
  const offered = o?.offered.length ? o.offered : r.notes.offered;
  return (
    <div className="space-y-2 text-sm">
      {o?.summary && <p className="break-words text-ink/90">{o.summary}</p>}
      {(who || reference) && (
        <p className="text-xs text-muted">
          {who && <>Spoke with {who}</>}
          {who && reference && " · "}
          {reference && (
            <>
              Reference <span className="num text-ink">{reference}</span>
            </>
          )}
        </p>
      )}
      {o && o.asks.length > 0 && (
        <ul className="space-y-1">
          {o.asks.map((a) => (
            <li key={a.ask} className="break-words">
              <span className="text-muted">{a.ask}:</span> {a.result}
            </li>
          ))}
        </ul>
      )}
      {offered.length > 0 && (
        <p className="break-words">
          <span className="eyebrow mr-1.5">They offered</span>
          {offered.join(" · ")}
        </p>
      )}
      {o && o.next.length > 0 && (
        <p className="break-words">
          <span className="eyebrow mr-1.5">Next</span>
          {o.next.join(" · ")}
        </p>
      )}
    </div>
  );
}

interface SheetCardProps {
  sheet: CallSheet;
  now: string;
  busy: boolean;
  blocked: boolean;
  onStart: (id: string, anyway?: boolean) => void;
  onStop: (id: string) => void;
}

/** One sheet: whom it calls and why, the call going now with its transcript, and the last few calls. */
function SheetCard({ sheet, now, busy, blocked, onStart, onStop }: SheetCardProps) {
  const [asking, setAsking] = useState(false);
  const live = sheet.live;
  return (
    <article className="card space-y-4 p-4 sm:p-5">
      <div>
        <h3 className="break-words font-display text-xl leading-snug text-ink">{sheet.title}</h3>
        <p className="mt-1 break-words text-sm text-muted">
          {sheet.to}
          {sheet.number && <span className="num ml-2">{sheet.number}</span>}
        </p>
      </div>

      {sheet.about && <p className="break-words text-sm text-ink/90">About {sheet.about}.</p>}
      <Asks sheet={sheet} done={live?.done ?? []} />
      <p className="text-xs text-muted">
        {sheet.talk ? "It asks for these itself, and rings you when it needs you." : "It rings you when someone answers; if you don't pick up, it asks for these itself."}
        {sheet.facts.length > 0 && <> It may tell them your {sheet.facts.join(", ")}, and nothing else.</>}
      </p>
      {sheet.notes && <p className="whitespace-pre-wrap break-words text-sm text-muted">{sheet.notes}</p>}
      {sheet.error && <p className="text-sm text-bad-ink">{sheet.error}</p>}
      {sheet.doubt && !live && <p className="break-words text-sm text-warn-ink">{sheet.doubt}</p>}

      {live ? (
        <div className="space-y-3 rounded-xl border border-line p-3 sm:p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="inline-flex items-center gap-2 text-sm text-ink">
              <span className="h-2 w-2 animate-pulse rounded-full bg-accent" aria-hidden />
              {PHASE[live.phase]}
              <span className="num text-xs text-muted">since {timeAgo(live.started, now)}</span>
            </p>
            <ActionButton icon={PhoneOff} label={busy ? "Hanging up…" : "Hang up"} tone="bad" disabled={busy} onClick={() => onStop(sheet.id)} />
          </div>
          <Transcript lines={live.transcript.slice(-14)} now={now} />
        </div>
      ) : (
        !sheet.error && (
          <div className="flex flex-wrap items-center gap-2">
            {asking ? (
              <>
                <span className="text-sm text-ink">
                  {sheet.doubt ? "You've checked it's theirs? Call" : "Call"} <span className="num">{sheet.number}</span> now?
                </span>
                <ActionButton
                  icon={Phone}
                  label={busy ? "Calling…" : sheet.doubt ? "Call anyway" : "Yes, call"}
                  tone={sheet.doubt ? "warn" : "accent"}
                  active
                  disabled={busy}
                  onClick={() => {
                    setAsking(false);
                    onStart(sheet.id, !!sheet.doubt);
                  }}
                />
                <ActionButton icon={X} label="Not now" tone="neutral" onClick={() => setAsking(false)} />
              </>
            ) : (
              <ActionButton icon={Phone} label={busy ? "Calling…" : "Call"} tone="accent" disabled={busy || blocked} onClick={() => setAsking(true)} />
            )}
          </div>
        )
      )}

      {sheet.past.length > 0 && (
        <div className="space-y-3 border-t border-line pt-3">
          <p className="smallcaps text-accent">Past calls</p>
          {sheet.past.map((r) => (
            <details key={r.started} className="space-y-2">
              <summary className="cursor-pointer text-sm text-ink">
                <span className="num" title={formatDateTime(r.started)}>
                  {timeAgo(r.started, now)}
                </span>
                <span className="text-muted"> · {r.status || "ended"}</span>
                {(r.outcome?.reference || r.notes.reference) && (
                  <span className="text-muted">
                    {" "}
                    · reference <span className="num">{r.outcome?.reference || r.notes.reference}</span>
                  </span>
                )}
              </summary>
              <div className="mt-2 space-y-3 pl-1">
                <Notes r={r} />
                <Transcript lines={r.transcript} now={now} />
              </div>
            </details>
          ))}
        </div>
      )}
    </article>
  );
}

/**
 * Phone calls Proxenos places for you: it waits on hold, says it's an automated assistant calling
 * for you, and rings you when a person answers, or asks for what the sheet lists. It never agrees
 * to pay. Each call starts only when you press Call.
 */
export function Calls() {
  const { data, error, busy, start, stop, clearError } = useCalls();

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load calls: ${error}`} /> : <ProseSkeleton label="Loading calls" />;
  }
  if (!data.vault.exists) return <NoVault path={data.vault.path} />;

  return (
    <div className="pb-24 md:pb-20">
      {error && <ErrorBanner message={error} onDismiss={clearError} />}
      <div className="space-y-6 p-4 sm:p-6">
        {data.missing.length > 0 && (
          <p className="rounded-xl border border-line p-3 text-sm text-muted">
            Calls go through your own Twilio account. Still to set: <span className="num text-ink">{data.missing.join(", ")}</span>,
            and the Twilio secrets in Settings. docs/calls.md has each step.
          </p>
        )}
        {data.sheets.length === 0 ? (
          <EmptyState icon={Phone} title="No call sheets yet" command="proxenos call list">
            A call sheet says whom to call, why, what to ask for and what the assistant may tell them. Write one at{" "}
            <code className="num">clones/calls/&lt;name&gt;.md</code> in the vault; docs/calls.md shows how.
          </EmptyState>
        ) : (
          data.sheets.map((s) => (
            <SheetCard
              key={s.id}
              sheet={s}
              now={data.now}
              busy={busy === s.id}
              blocked={busy !== null || data.missing.length > 0}
              onStart={(id, anyway) => void start(id, anyway)}
              onStop={(id) => void stop(id)}
            />
          ))
        )}
        <p className="text-xs text-muted">
          On hold it says nothing. To a person it says it&apos;s an automated assistant calling for you and that the call is
          transcribed, never that it&apos;s you. It never agrees to pay, settle or a payment plan, and gives no number that isn&apos;t
          on the sheet. The call goes through Twilio, which hears it to transcribe it and doesn&apos;t record it. A number your
          records have from just one message to you, and from nothing of yours, may be a scam&apos;s: it says so, and calls it
          only once you press Call anyway. <Command>proxenos call start &lt;name&gt;</Command>{" "}
          places one from a terminal.
        </p>
      </div>
    </div>
  );
}
