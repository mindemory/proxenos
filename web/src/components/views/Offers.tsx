"use client";

import { useEffect, useState } from "react";
import { ArrowRight, ArrowUp, TriangleAlert } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { Fold } from "@/components/ask/parts";
import { ChannelBadge, SentBadge } from "@/components/drafts/badges";
import { ErrorBanner, NoVault } from "@/components/EmptyState";
import { Bone } from "@/components/Skeleton";
import { formatDateTime, shortDate, timeAgo } from "@/lib/format";
import { useOffers } from "@/lib/offersClient";
import { OFFERS_MAX_GOAL, OFFERS_MONTHS, type OfferPrice, type OfferRow, type Offers as Comparison } from "@/lib/types";
import { cn } from "@/lib/utils";

// What was being written when the view was left, so coming back to it doesn't lose it.
let kept = "";

const CELL = "px-3 py-2.5 align-top";

function priced(p: OfferPrice): string {
  return p.what && p.price ? `${p.what}, ${p.price}` : p.what || p.price;
}

function Missing({ text = "not said" }: { text?: string }) {
  return <span className="text-faint">{text}</span>;
}

/** One row a counterpart, every price as they wrote it; what wasn't in their messages was left out. */
function Table({ rows, now }: { rows: OfferRow[]; now: string }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-line">
      <table className="w-full min-w-[52rem] text-sm">
        <caption className="sr-only">What each offered, as their messages say</caption>
        <thead>
          <tr className="text-left text-xs text-muted">
            {["Who", "First step", "The whole", "Credited", "Terms", "Last contact", "Still to ask"].map((h) => (
              <th key={h} scope="col" className="px-3 py-2.5 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line border-t border-line">
          {rows.map((r) => (
            <tr key={r.key}>
              <th scope="row" className={cn(CELL, "min-w-[10rem] text-left font-normal")}>
                <span className="text-ink">{r.name}</span>
                {r.people.length > 0 && (
                  <span className="block text-xs text-muted">{r.people.map((p) => (p.role ? `${p.name}, ${p.role}` : p.name)).join("; ")}</span>
                )}
                {r.error && <span className="block text-xs text-bad-ink">{r.error}</span>}
              </th>
              <td className={CELL}>{priced(r.first) || <Missing />}</td>
              <td className={CELL}>
                {priced(r.whole) || <Missing />}
                {r.prices.length > 0 && (
                  <ul className="mt-1 space-y-0.5 text-xs text-muted">
                    {r.prices.map((p) => (
                      <li key={`${p.what}-${p.price}`}>{priced(p)}</li>
                    ))}
                  </ul>
                )}
              </td>
              <td className={CELL}>{r.credited || <Missing />}</td>
              <td className={CELL}>
                {r.terms.length > 0 ? (
                  <ul className="space-y-0.5">
                    {r.terms.map((t) => (
                      <li key={t}>{t}</li>
                    ))}
                  </ul>
                ) : (
                  <Missing text="none said" />
                )}
              </td>
              <td className={cn(CELL, "whitespace-nowrap")}>
                <span className="num" title={formatDateTime(r.last)}>
                  {shortDate(r.last, now)}
                </span>
                <span className={cn("block text-xs", r.owes === "you" ? "text-warn-ink" : "text-muted")}>
                  {r.owes === "you" ? "you owe a reply" : "they owe a reply"}
                </span>
              </td>
              <td className={cn(CELL, "text-muted")}>{r.missing.length > 0 ? r.missing.join("; ") : <Missing text="nothing" />}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A row's reply as its errand stands: who it goes to and how, and the way to it in Errands. */
function Reply({ row, onErrand }: { row: OfferRow; onErrand?: (id: string) => void }) {
  const reply = row.reply;
  if (!reply) return null;
  const where = reply.address || (reply.state === "waiting" ? "no address yet" : `their ${reply.channel} chat`);
  return (
    <li className="space-y-2 rounded-xl border border-line-strong bg-surface-2 p-3.5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        <ChannelBadge channel={reply.channel} />
        <span className="min-w-0 break-words text-sm text-muted">
          To <span className="text-ink/90">{reply.to}</span> · {where}
        </span>
        {reply.state === "sent" ? (
          <SentBadge />
        ) : reply.state === "done" ? (
          <span className="text-xs text-muted">No longer needed</span>
        ) : (
          <span
            className={cn(
              "inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs",
              reply.state === "ready" ? "border-ok-line bg-ok-bg text-ok-ink" : "border-warn-line bg-warn-bg text-warn-ink",
            )}
          >
            {reply.state === "ready" ? "Ready to send" : "Waiting on an address"}
          </span>
        )}
      </div>
      <Fold label={reply.subject ? `“${reply.subject}”` : "The message"}>
        <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-ink/90">{reply.body}</p>
      </Fold>
      {onErrand && (
        <ActionButton
          icon={ArrowRight}
          label={reply.state === "sent" || reply.state === "done" ? "See it in Errands" : "Edit and send in Errands"}
          name={`${reply.state === "sent" || reply.state === "done" ? "See it in Errands" : "Edit and send in Errands"}: the reply to ${reply.to}`}
          tone="accent"
          onClick={() => onErrand(reply.errand)}
        />
      )}
    </li>
  );
}

function ComparisonCard({ offers, now, onErrand }: { offers: Comparison; now: string; onErrand?: (id: string) => void }) {
  const dropped = offers.rows.filter((r) => r.unconfirmed.length > 0);
  const replies = offers.rows.filter((r) => r.reply);
  return (
    <article className="card min-w-0 space-y-4 p-4 sm:p-5">
      <div className="space-y-1">
        <h2 className="text-[1.0625rem] font-medium leading-snug text-ink">{offers.goal}</h2>
        <p className="text-xs text-muted">
          <span title={formatDateTime(offers.updated)}>
            Compared <span className="num">{timeAgo(offers.updated, now)}</span>
          </span>
          {" · "}from your mail and chats since <span className="num">{shortDate(offers.since, now)}</span>
          {offers.project && <> · in the brief of {offers.project}</>}
        </p>
      </div>

      {offers.status === "working" && <p className="text-sm text-accent">Comparing them again now; this is the last comparison.</p>}
      {offers.status === "failed" && (
        <div className="flex items-start gap-2.5 rounded-xl border border-bad-line bg-bad-bg p-3 text-sm text-bad-ink">
          <TriangleAlert size={16} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
          <span className="min-w-0 break-words">{offers.error ?? "It didn't finish."}</span>
        </div>
      )}

      {offers.rows.length === 0 ? (
        offers.status === "done" && (
          <p className="text-sm text-muted">Nothing in your mail or chats over that time reads as an offer for it. Try the words they&apos;d use.</p>
        )
      ) : (
        <Table rows={offers.rows} now={now} />
      )}

      {offers.note && (
        <div className="space-y-1">
          <p className="smallcaps">What to compare on</p>
          <p className="text-sm leading-relaxed text-ink/90">{offers.note}</p>
        </div>
      )}

      {dropped.length > 0 && (
        <p className="text-xs leading-relaxed text-muted">
          Left out, as their messages don&apos;t say it: {dropped.map((r) => `${r.name} (${r.unconfirmed.join(", ")})`).join("; ")}.
        </p>
      )}

      {replies.length > 0 && (
        <section aria-label="Replies" className="space-y-2">
          <p className="smallcaps">Replies asking for what&apos;s missing</p>
          <ul className="space-y-2">
            {replies.map((r) => (
              <Reply key={r.key} row={r} onErrand={onErrand} />
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}

interface OffersProps {
  /** Open a reply's errand in Errands, to edit and send it there. */
  onErrand?: (id: string) => void;
}

/**
 * What several people or firms offered for one goal, side by side from your own mail and chats,
 * with a reply to each asking for what's missing. Every price is as they wrote it; nothing goes out
 * until you press Send on a reply in Errands.
 */
export function Offers({ onErrand }: OffersProps) {
  const { data, error, clearError, waiting, start } = useOffers();
  const [goal, setGoal] = useState(kept);
  const [months, setMonths] = useState<number>(12);
  const [project, setProject] = useState("");
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    kept = goal;
  }, [goal]);

  if (data && !data.vault.exists) return <NoVault path={data.vault.path} />;

  const busy = data?.job?.state === "running" || waiting;
  const working = data?.comparisons.find((c) => c.status === "working") ?? null;
  const canStart = goal.trim() !== "" && goal.length <= OFFERS_MAX_GOAL && !starting && !busy;

  const submit = async () => {
    if (!canStart) return;
    setStarting(true);
    const ok = await start({ goal: goal.trim(), months, project: project || null });
    setStarting(false);
    if (ok) setGoal("");
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 pb-24 sm:p-6 md:pb-20">
      {error && <ErrorBanner message={error} onDismiss={data ? clearError : undefined} />}

      <section aria-label="A new comparison" className="card space-y-3 p-3 sm:p-4">
        <textarea
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void submit();
          }}
          rows={2}
          maxLength={OFFERS_MAX_GOAL}
          aria-label="What the offers are for"
          placeholder="What are you choosing? “An immigration lawyer for my visa”, “a contractor for the kitchen”, “a flat near work”."
          className="w-full resize-none bg-transparent text-[0.9375rem] leading-relaxed text-ink placeholder:text-faint focus:outline-none"
        />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted">
            <label className="inline-flex items-center gap-2">
              <span>Look back</span>
              <select
                value={months}
                onChange={(e) => setMonths(Number(e.target.value))}
                className="rounded-full border border-line-strong bg-surface px-3 py-1 text-sm text-ink hover:border-accent/40"
              >
                {OFFERS_MONTHS.map((m) => (
                  <option key={m} value={m}>
                    {m} months
                  </option>
                ))}
              </select>
            </label>
            {data && data.projects.length > 0 && (
              <label className="inline-flex items-center gap-2">
                <span>Add to the brief of</span>
                <select
                  value={project}
                  onChange={(e) => setProject(e.target.value)}
                  className="max-w-[14rem] rounded-full border border-line-strong bg-surface px-3 py-1 text-sm text-ink hover:border-accent/40"
                >
                  <option value="">no project</option>
                  {data.projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          <ActionButton icon={ArrowUp} label={starting ? "Starting…" : "Compare"} tone="accent" disabled={!canStart} onClick={() => void submit()} />
        </div>
        <p className="text-xs text-muted">
          {busy
            ? "One comparison at a time: start the next when this one is done."
            : "It reads what each person or firm wrote you about it, and drafts a reply to each. Nothing goes out until you press Send."}
        </p>
      </section>

      {busy && !working && (
        <section aria-live="polite" className="card p-4 sm:p-5">
          <p className="smallcaps text-accent">Comparing</p>
          <p className="mt-1 text-sm text-muted">Finding who wrote to you about it.</p>
        </section>
      )}

      {data === null ? (
        error ? null : (
          <div className="card space-y-3 p-5" aria-hidden="true">
            <Bone className="h-4 w-1/4" />
            <Bone className="h-4 w-full" />
            <Bone className="h-4 w-4/5" />
          </div>
        )
      ) : data.comparisons.length === 0 ? (
        !busy && (
          <p className="max-w-2xl text-sm leading-relaxed text-muted">
            Say what you&apos;re choosing between offers for: a lawyer, a contractor, a flat, a clinic, a job. It finds who wrote to you about it in
            your mail and chats, a firm by its domain and a person by their address or chat, and lays out side by side what each offered: the
            first step and its price, the whole and its price, what&apos;s credited, their terms, and who owes whom a reply. Every price is as
            they wrote it; one their messages don&apos;t hold is left out. Then it drafts a reply to each, in your voice, asking for what&apos;s
            missing, such as a flat fee for the whole, and may say someone else offers less, never who. Each waits in Errands for your Send.
          </p>
        )
      ) : (
        <section aria-label="Comparisons" className="space-y-4">
          {data.comparisons.map((c) => (
            <ComparisonCard key={c.slug} offers={c} now={data.now} onErrand={onErrand} />
          ))}
        </section>
      )}
    </div>
  );
}
