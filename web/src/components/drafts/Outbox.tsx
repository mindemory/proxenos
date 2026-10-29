"use client";

import { useState } from "react";
import { Check, ChevronRight, X } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { Bone } from "@/components/Skeleton";
import { useOutbox } from "@/lib/client";
import { formatDateTime, formatTime, timeAgo } from "@/lib/format";
import { OUTBOX_LIMITS, OUTBOX_LOG_SHOWN, outboxChannelLabel, outboxRouteHint, outboxRouteLabel } from "@/lib/outbox";
import { OUTBOX_CHANNELS, type OutboxChannel, type OutboxState } from "@/lib/types";
import { cn } from "@/lib/utils";

const SECTION = "px-4 sm:px-6 py-3 border-b border-line";

/** Always these two, so the way to turn them on is there before the first sync has run. */
const ALWAYS = ["email", "whatsapp"];

/**
 * A switch, as a button: its position is the saved setting. The pseudo-element makes the touch
 * target 44px tall without making the track bigger.
 */
function Switch({
  id,
  on,
  disabled,
  label,
  describedBy,
  onToggle,
}: {
  id?: string;
  on: boolean;
  disabled: boolean;
  label?: string;
  describedBy?: string;
  onToggle: () => void;
}) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      aria-describedby={describedBy}
      disabled={disabled}
      onClick={onToggle}
      className={cn(
        "relative inline-flex h-6 w-10 flex-shrink-0 items-center rounded-full border transition-colors",
        "after:absolute after:-inset-x-1.5 after:-inset-y-2.5 after:content-['']",
        "disabled:cursor-not-allowed disabled:opacity-50",
        on ? "border-ok-line bg-ok-bg" : "border-line-strong bg-surface-2",
      )}
    >
      <span
        aria-hidden="true"
        className={cn("block h-4 w-4 rounded-full transition-transform", on ? "translate-x-5 bg-ok-ink" : "translate-x-0.5 bg-muted")}
      />
    </button>
  );
}

/**
 * A small whole-number box. What is typed is saved when the reader leaves the box or presses
 * Enter, and only if it is a whole number inside the limits; Escape puts the saved value back.
 */
function NumberField({
  value,
  min,
  max,
  label,
  disabled,
  onCommit,
  onReject,
}: {
  value: number;
  min: number;
  max: number;
  label: string;
  disabled: boolean;
  onCommit: (n: number) => Promise<unknown>;
  onReject: (message: string) => void;
}) {
  // The text while it is being edited, and until the save that follows has come back.
  const [edit, setEdit] = useState<string | null>(null);

  const commit = async () => {
    if (edit === null) return;
    const typed = edit.trim();
    const n = Number(typed);
    if (typed === "" || n === value) {
      setEdit(null);
    } else if (!Number.isInteger(n) || n < min || n > max) {
      setEdit(null);
      onReject(`${label} needs a whole number from ${min} to ${max}.`);
    } else {
      await onCommit(n);
      setEdit(null);
    }
  };

  return (
    <input
      value={edit ?? String(value)}
      onChange={(e) => setEdit(e.target.value)}
      onBlur={() => void commit()}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur();
        else if (e.key === "Escape") setEdit(null);
      }}
      disabled={disabled}
      inputMode="numeric"
      autoComplete="off"
      spellCheck={false}
      aria-label={label}
      className="num w-12 rounded-lg border border-line-strong bg-bg px-1 py-1 text-center text-[16px] text-ink focus:border-accent/60 focus:outline-none disabled:opacity-60 sm:text-sm"
    />
  );
}

/** What a channel's row says it is: where it stands, in the words of the sync's last look. */
function channelStatus(channel: string, state: OutboxState | null): { text: string; className: string } {
  if (!state) return { text: "Waiting for the first sync", className: "text-muted" };
  if (!state.routes[channel]) return { text: "No way to send yet", className: "text-muted" };
  if (!state.earned[channel]) return { text: "Not earned yet", className: "text-muted" };
  return { text: "Ready", className: "text-ok-ink" };
}

/**
 * Replies that go out on their own: the master switch, each app's rule and track record, the
 * replies waiting out their window to be cancelled, and what has been sent. Everything starts
 * off, and the panel reads the same with none of the outbox's files there yet. A change shows
 * only once it is saved.
 */
export function Outbox() {
  const { data, error, saving, problem, cancelledNow, change, cancel, report } = useOutbox();
  const [showLog, setShowLog] = useState(false);

  if (!data) {
    return (
      <section aria-label="Outbox" className={SECTION}>
        <h2 className="smallcaps">Outbox</h2>
        {error ? (
          <p className="mt-2 text-sm text-bad-ink">Couldn&apos;t load the outbox: {error}</p>
        ) : (
          <Bone className="mt-3 h-5 w-64 max-w-full" />
        )}
      </section>
    );
  }

  const { rules, state } = data;
  const hidden = new Set(data.cancelled);
  // Replies cancelled before this visit are gone; the ones cancelled now stay, marked as such.
  const queue = (state?.queue ?? []).filter((q) => cancelledNow.has(q.draft_id) || !hidden.has(q.draft_id));
  const shown = OUTBOX_CHANNELS.filter(
    (c) =>
      ALWAYS.includes(c) ||
      rules.channels[c].on ||
      state?.routes[c] !== undefined ||
      state?.closeness[c] !== undefined,
  );
  const sent = data.log.filter((e) => e.ok).length;
  const failed = data.log.length - sent;

  const setChannel = (c: OutboxChannel, edit: { on?: boolean; min_closeness?: number; min_measured?: number }, done: string) =>
    change({ channel: c, ...edit }, done);

  return (
    <section aria-label="Outbox" className={cn(SECTION, "space-y-3")}>
      <h2 className="smallcaps">Outbox</h2>

      <div>
        <label htmlFor="outbox-enabled" className="flex min-h-11 cursor-pointer items-center gap-3 text-ink">
          <Switch
            id="outbox-enabled"
            on={rules.enabled}
            disabled={saving}
            describedBy="outbox-about"
            onToggle={() =>
              void change(
                { enabled: !rules.enabled },
                rules.enabled ? "Nothing will go out on its own" : "Replies can go out on their own now",
              )
            }
          />
          Let replies go out on their own
          <span aria-hidden="true" className={cn("ml-auto text-xs", rules.enabled ? "text-ok-ink" : "text-muted")}>
            {rules.enabled ? "On" : "Off"}
          </span>
        </label>
        <p id="outbox-about" className="mt-1 max-w-2xl text-sm leading-relaxed text-muted">
          Only replies to one person, with nothing left for you to fill in or decide, and only where that
          app&apos;s replies have gone out nearly as drafted. Each waits until the next sync, about 15 minutes, so you can
          cancel it.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
        <p className="flex items-center gap-2">
          At most
          <NumberField
            value={rules.daily_limit}
            min={OUTBOX_LIMITS.dailyLimit.min}
            max={OUTBOX_LIMITS.dailyLimit.max}
            label="The daily limit"
            disabled={saving}
            onCommit={(n) => change({ daily_limit: n }, `Limit set to ${n} a day`)}
            onReject={report}
          />
          a day
        </p>
        {state && (
          <p>
            <span className="num text-ink">{state.sent_today}</span> sent today
            {state.generated && (
              <>
                <span className="mx-1.5 text-faint" aria-hidden="true">
                  ·
                </span>
                <span title={formatDateTime(state.generated)}>
                  last sync <span className="num text-ink">{timeAgo(state.generated, data.now)}</span>
                </span>
              </>
            )}
          </p>
        )}
      </div>

      {problem && (
        <p role="alert" className="text-sm text-bad-ink">
          {problem}
        </p>
      )}

      <ul className="divide-y divide-line border-y border-line">
        {shown.map((c) => {
          const rule = rules.channels[c];
          const label = outboxChannelLabel(c);
          const route = state?.routes[c] ?? null;
          const record = state?.closeness[c];
          const status = channelStatus(c, state);
          const hint = state && !route ? outboxRouteHint(c) : "";
          return (
            <li key={c} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 py-3 sm:grid-cols-[minmax(0,1fr)_auto_auto]">
              <div className="col-start-1 row-start-1 min-w-0">
                <p className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <span className="text-ink">{label}</span>
                  <span className={cn("text-xs", status.className)}>{status.text}</span>
                </p>
                <p className="text-sm text-muted">
                  {record ? (
                    <>
                      <span className="num text-ink">{record.n}</span> measured,{" "}
                      <span className="num text-ink">{Math.round(record.mean * 100)}%</span> close
                    </>
                  ) : (
                    "Nothing measured yet"
                  )}
                  {route && <span className="text-faint"> · via {outboxRouteLabel(route)}</span>}
                </p>
                {hint && <p className="text-xs text-faint">{hint}</p>}
              </div>

              <div className="col-start-2 row-start-1 sm:col-start-3">
                <Switch
                  on={rule.on}
                  // Switching off is always possible; switching on needs a way to send.
                  disabled={saving || (!rule.on && !route)}
                  label={`Let ${label} replies go out on their own`}
                  onToggle={() =>
                    void setChannel(
                      c,
                      { on: !rule.on },
                      rule.on ? `${label} replies will wait for you` : `${label} replies can go out on their own`,
                    )
                  }
                />
              </div>

              <p className="col-span-2 col-start-1 row-start-2 flex flex-wrap items-center gap-x-1.5 gap-y-1.5 text-sm text-muted sm:col-span-1 sm:col-start-2 sm:row-start-1">
                At least
                <NumberField
                  value={rule.min_measured}
                  min={OUTBOX_LIMITS.measured.min}
                  max={OUTBOX_LIMITS.measured.max}
                  label={`${label}: replies measured`}
                  disabled={saving}
                  onCommit={(n) => setChannel(c, { min_measured: n }, `${label}: ${n} measured needed`)}
                  onReject={report}
                />
                measured and
                <span className="inline-flex items-center">
                  <NumberField
                    value={Math.round(rule.min_closeness * 100)}
                    min={Math.round(OUTBOX_LIMITS.closeness.min * 100)}
                    max={Math.round(OUTBOX_LIMITS.closeness.max * 100)}
                    label={`${label}: percent close`}
                    disabled={saving}
                    onCommit={(n) => setChannel(c, { min_closeness: n / 100 }, `${label}: ${n}% close needed`)}
                    onReject={report}
                  />
                  % close
                </span>
              </p>
            </li>
          );
        })}
      </ul>

      {queue.length > 0 ? (
        <div>
          <h3 className="smallcaps">Waiting to go out</h3>
          <ul className="mt-1 divide-y divide-line">
            {queue.map((q) => (
              <li key={q.draft_id} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="break-words text-sm text-ink">
                    {q.to || "Someone"} <span className="text-muted">on {outboxChannelLabel(q.channel)}</span>
                  </p>
                  <p className="text-xs text-muted">
                    {cancelledNow.has(q.draft_id) ? (
                      "It won't go out."
                    ) : (
                      <>
                        Goes out at the next sync after <span className="num text-ink">{formatTime(q.sends_at) || "its window ends"}</span>
                      </>
                    )}
                  </p>
                </div>
                {cancelledNow.has(q.draft_id) ? (
                  <span className="inline-flex items-center gap-1 text-xs text-ok-ink">
                    <Check size={12} />
                    Cancelled
                  </span>
                ) : (
                  <ActionButton icon={X} label="Cancel" tone="bad" onClick={() => void cancel(q.draft_id)} />
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        rules.enabled && <p className="text-sm text-muted">Nothing is waiting to go out.</p>
      )}

      {data.log.length > 0 && (
        <div>
          <button
            onClick={() => setShowLog((v) => !v)}
            aria-expanded={showLog}
            className="flex items-baseline gap-1.5 text-left text-sm text-muted transition-colors hover:text-ink"
          >
            <ChevronRight size={15} className={cn("self-center transition-transform", showLog && "rotate-90")} />
            Sent on their own
            <span className="num text-ink">({data.log.length >= OUTBOX_LOG_SHOWN ? `${sent}+` : sent})</span>
            {failed > 0 && <span className="text-xs text-bad-ink">{failed} failed</span>}
          </button>
          {showLog && (
            <ul className="mt-1 divide-y divide-line">
              {data.log.map((e, i) => (
                <li key={`${e.at}-${e.draft_id}-${i}`} className="py-2 text-sm">
                  <p className="break-words">
                    <span className="text-ink">{e.to || "Someone"}</span>{" "}
                    <span className="text-muted">on {outboxChannelLabel(e.channel)}</span>
                    <span className="mx-1.5 text-faint" aria-hidden="true">
                      ·
                    </span>
                    <span className="num text-muted">{formatDateTime(e.at)}</span>
                    {e.via && <span className="text-faint"> · via {outboxRouteLabel(e.via)}</span>}
                  </p>
                  {e.ok ? (
                    <p className="inline-flex items-center gap-1 text-xs text-ok-ink">
                      <Check size={12} />
                      Sent
                    </p>
                  ) : (
                    <p className="break-words text-xs text-bad-ink">Failed{e.error ? `: ${e.error}` : ""}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
