"use client";

import { useEffect, useState } from "react";
import { Check, Copy, FileText, Paperclip, Send, TriangleAlert, X } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { Fold, QuestionText } from "@/components/ask/parts";
import { ChannelBadge, SentBadge } from "@/components/drafts/badges";
import { useToast } from "@/components/Toasts";
import { copyText } from "@/lib/client";
import { channelLabel } from "@/lib/drafts";
import { formatDateTime, timeAgo } from "@/lib/format";
import type { Errand, ErrandCv, ErrandEdits, ErrandMessage, ErrandStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const ADDRESS = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$/;
const PLACEHOLDER = /\[[^\]\n]{1,80}\]/;

const STATUS: Record<ErrandStatus, { label: string; tone: string }> = {
  working: {
    label: "Working on it",
    tone: "border-accent/40 bg-accent/10 text-accent",
  },
  ready: {
    label: "Ready to send",
    tone: "border-ok-line bg-ok-bg text-ok-ink",
  },
  waiting: {
    label: "Waiting on you",
    tone: "border-warn-line bg-warn-bg text-warn-ink",
  },
  sent: { label: "Sent", tone: "border-ok-line bg-ok-bg text-ok-ink" },
  failed: {
    label: "Didn't finish",
    tone: "border-bad-line bg-bad-bg text-bad-ink",
  },
  dropped: {
    label: "Dropped",
    tone: "border-line-strong bg-surface-2 text-muted",
  },
};

const INPUT =
  "w-full rounded-lg border border-line-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-faint focus:border-accent/60 focus:outline-none";

/** What's left before Send can go: null when nothing is. */
function blocker(m: ErrandMessage, address: string, subject: string, body: string): string | null {
  const email = m.channel === "email" || address !== m.address;
  if (!body.trim()) return "The message is empty.";
  if (PLACEHOLDER.test(body)) return "Fill in the [placeholder] first.";
  if (!m.via && !ADDRESS.test(address.trim())) {
    return m.channel === "email"
      ? "Type their email address to send it."
      : `There's no ${channelLabel(m.channel)} chat with ${m.to} to send it in yet: copy it there, or type an email address.`;
  }
  if (address.trim() && !ADDRESS.test(address.trim())) return "That isn't an email address.";
  if (email && !subject.trim()) return "Give the email a subject.";
  return null;
}

/** One message the errand wrote: who it's to and how, editable, and its Send. */
function MessageBox({
  message,
  cv,
  busy,
  onSend,
}: {
  message: ErrandMessage;
  cv: ErrandCv | null;
  busy: boolean;
  onSend: (edits: ErrandEdits) => void;
}) {
  const notify = useToast();
  const [address, setAddress] = useState(message.address);
  const [subject, setSubject] = useState(message.subject);
  const [body, setBody] = useState(message.body);
  const [confirm, setConfirm] = useState(false);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1600);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const sent = message.state === "sent";
  const email = message.channel === "email" || (address.trim() !== "" && address !== message.address);
  const why = sent ? null : blocker(message, address, subject, body);
  const what = message.role === "intro" ? "asking for an introduction" : null;

  const copy = async () => {
    const ok = await copyText(email && subject ? `Subject: ${subject}\n\n${body}` : body);
    if (!ok) return notify("Couldn't reach the clipboard. Select the text and copy it by hand.", "info");
    notify("Copied to the clipboard", "ok");
    setCopied(true);
  };

  const send = () => {
    const edits: ErrandEdits = {};
    if (address.trim() !== message.address) edits.address = address.trim();
    if (subject !== message.subject) edits.subject = subject;
    if (body !== message.body) edits.body = body;
    setConfirm(false);
    onSend(edits);
  };

  return (
    <div className="space-y-3 rounded-xl border border-line-strong bg-surface-2 p-3.5 sm:p-4">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        <span className="smallcaps">{message.role === "intro" ? "Note" : "Message"}</span>
        <ChannelBadge channel={message.channel} />
        <span className="min-w-0 break-words text-sm text-muted">
          To <span className="text-ink/90">{message.to}</span>
          {what && <span className="text-faint"> · {what}</span>}
        </span>
        {sent && <SentBadge />}
      </div>

      {message.evidence && message.address && (
        <p className="text-xs text-muted">
          <span className="text-ink/90">{message.address}</span>: {message.evidence}.
        </p>
      )}
      {!sent && !message.via && (
        <label className="block space-y-1">
          <span className="text-xs text-muted">
            {message.channel === "email" ? "Their email address" : "Or their email address"}, when you have it (it&apos;s never guessed)
          </span>
          <input
            type="email"
            inputMode="email"
            autoComplete="off"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="name@example.com"
            className={INPUT}
          />
        </label>
      )}
      {email && (
        <input
          aria-label="Subject"
          value={subject}
          disabled={sent}
          onChange={(e) => setSubject(e.target.value)}
          placeholder="Subject"
          className={cn(INPUT, "font-medium")}
        />
      )}
      <textarea
        aria-label="Message"
        value={body}
        disabled={sent}
        onChange={(e) => setBody(e.target.value)}
        rows={Math.min(16, Math.max(5, body.split("\n").length + 2))}
        className={cn(INPUT, "resize-y leading-relaxed")}
      />
      {message.attach && cv && (
        <p className="inline-flex items-center gap-1.5 text-xs text-muted">
          <Paperclip size={13} aria-hidden="true" />
          {cv.name}
        </p>
      )}

      {sent ? (
        <p className="text-xs text-muted" title={formatDateTime(message.sentAt)}>
          Sent {message.sentAt ? formatDateTime(message.sentAt) : ""}
          {message.address ? ` to ${message.address}` : ""}.
        </p>
      ) : (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-2">
            {confirm ? (
              <>
                <ActionButton
                  icon={Send}
                  label={`Send to ${address.trim() || message.to}`}
                  tone="ok"
                  active
                  fillWhenActive
                  onClick={send}
                />
                <ActionButton icon={X} label="Not yet" tone="neutral" onClick={() => setConfirm(false)} />
              </>
            ) : (
              <ActionButton icon={Send} label="Send" tone="accent" disabled={busy || why !== null} onClick={() => setConfirm(true)} />
            )}
            <ActionButton
              icon={copied ? Check : Copy}
              label={copied ? "Copied" : "Copy"}
              tone="neutral"
              active={copied}
              onClick={() => void copy()}
            />
          </div>
          {why && <p className="text-xs text-muted">{why}</p>}
          {busy && <p className="text-xs text-muted">A Send is going; this one waits until it&apos;s done.</p>}
        </div>
      )}
    </div>
  );
}

interface ErrandCardProps {
  errand: Errand;
  now: string;
  /** A Send or Drop is going. */
  busy: boolean;
  onSend: (index: number, edits: ErrandEdits) => void;
  onDrop: () => void;
}

/** One errand: what it was, where it stands, what it wrote, and every step it took to get there. */
export function ErrandCard({ errand, now, busy, onSend, onDrop }: ErrandCardProps) {
  const status = STATUS[errand.status];
  const done = errand.status === "sent" || errand.status === "dropped";
  return (
    <article id={`errand-${errand.id}`} className="card flex min-w-0 scroll-mt-20 flex-col gap-4 p-4 sm:p-5">
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
          <span className={cn("inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs", status.tone)}>{status.label}</span>
          {errand.created && (
            <span className="text-xs text-muted" title={formatDateTime(errand.created)}>
              <span className="num">{timeAgo(errand.created, now)}</span>
            </span>
          )}
        </div>
        <QuestionText text={errand.goal} />
      </div>

      {errand.status === "failed" && (
        <div className="flex items-start gap-2.5 rounded-xl border border-bad-line bg-bad-bg p-3 text-sm text-bad-ink">
          <TriangleAlert size={16} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
          <span className="min-w-0 break-words">{errand.error ?? "It didn't finish."}</span>
        </div>
      )}

      {errand.summary && errand.status !== "failed" && errand.status !== "working" && (
        <p className="text-sm leading-relaxed text-ink">{errand.summary}</p>
      )}
      {errand.who && <p className="text-sm leading-relaxed text-muted">{errand.who}</p>}

      {errand.messages.map((m, i) => (
        <MessageBox
          // A change on the server (a Send, a night's look for an address) starts the box afresh.
          key={`${i}-${errand.updated}`}
          message={m}
          cv={errand.cv}
          busy={busy}
          onSend={(edits) => onSend(i, edits)}
        />
      ))}

      {(errand.cv || errand.needs.length > 0) && (
        <div className="space-y-2 border-l-2 border-line-strong pl-3 text-xs leading-relaxed text-muted">
          {errand.cv && (
            <div>
              <p className="inline-flex items-center gap-1.5">
                <FileText size={13} aria-hidden="true" />
                <span>
                  <span className="font-medium text-ink">{errand.cv.name}</span>, made {formatDateTime(errand.cv.made)}, from{" "}
                  {errand.cv.where}
                </span>
              </p>
              {errand.cv.notes.length > 0 && (
                <ul className="mt-1 list-disc space-y-0.5 pl-4 text-warn-ink">
                  {errand.cv.notes.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {errand.needs.length > 0 && (
            <div>
              <p className="font-medium text-ink">Only you can say</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                {errand.needs.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {errand.steps.length > 0 && (
        <Fold label={`What it did, step by step (${errand.steps.length})`}>
          <ol className="space-y-2.5">
            {errand.steps.map((s, i) => (
              <li key={`${i}-${s.at}`} className="text-sm leading-relaxed">
                <span className="font-medium text-ink">{s.title}</span>
                {s.at && (
                  <span className="ml-2 text-xs text-faint" title={formatDateTime(s.at)}>
                    {timeAgo(s.at, now)}
                  </span>
                )}
                <p className="whitespace-pre-wrap break-words text-muted">{s.detail}</p>
              </li>
            ))}
          </ol>
        </Fold>
      )}

      {!done && errand.status !== "working" && (
        <div>
          <ActionButton icon={X} label="Drop it" tone="bad" disabled={busy} onClick={onDrop} />
        </div>
      )}
    </article>
  );
}
