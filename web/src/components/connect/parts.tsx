"use client";

import { Check, Copy, LoaderCircle, X } from "lucide-react";
import { useState } from "react";

import { Command } from "@/components/EmptyState";
import { SourceChip } from "@/components/SourceBadge";
import { useToast } from "@/components/Toasts";
import { formatDateTime, timeAgo } from "@/lib/format";
import type { ConnectJob, ConnectSource } from "@/lib/types";
import { cn } from "@/lib/utils";

interface SourceCopy {
  label: string;
  /** Which source's icon and colour it takes, when that isn't its own id. */
  kind?: string;
  /** How to connect it until it has a button of its own. */
  how: string;
  command?: string;
}

/** Every source the page lists: its name, and how to connect it for now. */
export const SOURCE_COPY: Record<string, SourceCopy> = {
  applemail: {
    label: "Apple Mail",
    kind: "email",
    how: "Email from every account in the Mail app on this Mac. Nothing to sign in to here.",
  },
  gmail: { label: "Gmail", kind: "email", how: "Your mail, read over IMAP and kept current. One sign-in per account." },
  microsoft: {
    label: "Microsoft 365 and Outlook",
    kind: "email",
    how: "Your mail and calendar, read through Microsoft's sign-in and kept current, on any computer. One sign-in per account.",
  },
  gcalendar: {
    label: "Google Calendar",
    kind: "calendar",
    how: "Your calendar, a year back and two months ahead, read through a read-only Google sign-in. One per account.",
  },
  whatsapp: { label: "WhatsApp", how: "Your messages and groups, from WhatsApp for Mac's own store on this computer." },
  slack: { label: "Slack", how: "Your messages in each workspace, read with slackdump signed in as you. Add each workspace once." },
  beeper: {
    label: "Beeper",
    how: "Instagram, Messenger, X and LinkedIn chats, read through Beeper Desktop. It's free for up to 5 accounts, so connect only those networks there: WhatsApp, Slack and email are read directly.",
  },
  strava: { label: "Strava", how: "With a Strava app's ID and secret in .env, sign in once:", command: "proxenos auth strava" },
  bluesky: { label: "Bluesky", how: "Your public posts. Put your handle in .env as PROXENOS_BLUESKY_HANDLE." },
  mentions: { label: "Papers and mentions", how: "News mentions and your papers. Put your full name in .env as PROXENOS_FULL_NAME." },
  linkedin: { label: "LinkedIn", how: "Settings, Data privacy, Get a copy of your data." },
  twitter: { label: "X", how: "Settings, Your account, Download an archive of your data." },
  instagram: {
    label: "Instagram",
    how: "Accounts Center, Your information and permissions, Download your information. JSON, all time, with messages.",
  },
  facebook: {
    label: "Facebook",
    how: "Accounts Center, Your information and permissions, Download your information. JSON, all time, with messages.",
  },
  threads: { label: "Threads", how: "The same Download your information page, with Threads picked." },
  calendar: { label: "Calendar export", how: "Google Takeout, Calendar, or any calendar's .ics export." },
  drive: { label: "Google Drive", how: "Google Takeout, Drive." },
  photos: { label: "Google Photos", how: "Google Takeout, Google Photos. Only dates, places and people are read." },
  keep: { label: "Google Keep", how: "Google Takeout, Keep." },
  gtasks: { label: "Google Tasks", how: "Google Takeout, Tasks." },
  youtube: { label: "YouTube", how: "Google Takeout, YouTube and YouTube Music. Pick JSON if it's offered." },
  chrome: { label: "Chrome history", how: "Google Takeout, Chrome." },
  email: {
    label: "Other email",
    kind: "email",
    how: "An mbox file, from Takeout's Mail or your mail client:",
    command: "proxenos ingest email --account NAME --mbox PATH",
  },
  spotify: { label: "Spotify", how: "Account, Privacy settings, Extended streaming history. It can take up to 30 days." },
  letterboxd: { label: "Letterboxd", how: "Settings, Data, Export your data." },
  notes: {
    label: "Notes and PDFs",
    how: "A Notion export, an Obsidian vault or a folder of PDFs:",
    command: "proxenos ingest notes --export DIR",
  },
  website: { label: "Your website", how: "Its local git repo, as PROXENOS_WEBSITE_REPO in .env." },
};

export function copyFor(id: string): SourceCopy {
  return SOURCE_COPY[id] ?? { label: id.charAt(0).toUpperCase() + id.slice(1), how: "" };
}

/** Text to copy, in a box with a copy button: a path or an address, as opposed to a shell command. */
export function CopyBox({ text, what }: { text: string; what: string }) {
  const notify = useToast();
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard?.writeText(text).then(
      () => {
        setCopied(true);
        notify(`${what} copied`, "ok");
        window.setTimeout(() => setCopied(false), 1600);
      },
      () => {
        // No clipboard (an insecure context or a denied permission): the text is still there to select.
      },
    );
  };
  const Icon = copied ? Check : Copy;
  return (
    <div className="flex items-start gap-2 rounded-xl border border-line-strong bg-surface-2 py-2 pl-3.5 pr-2">
      <code className="num min-w-0 flex-1 select-all break-all text-sm text-ink">{text}</code>
      <button
        type="button"
        onClick={copy}
        title="Copy"
        className="-my-0.5 flex-shrink-0 rounded-lg p-1.5 text-muted transition-colors hover:text-ink"
      >
        <Icon size={14} aria-hidden="true" />
        <span className="sr-only">{copied ? "Copied" : `Copy the ${what.toLowerCase()}`}</span>
      </button>
    </div>
  );
}

/** A numbered list of steps, in the page's plain words. */
export function Steps({ children }: { children: React.ReactNode }) {
  return (
    <ol className="list-decimal space-y-1.5 pl-5 text-sm leading-relaxed text-muted marker:text-faint marker:num">{children}</ol>
  );
}

export function Chip({ id }: { id: string }) {
  return <SourceChip kind={copyFor(id).kind ?? id} size={36} />;
}

/** Connected or not, as a dot and a word. */
export function StatePill({ on, label, tone }: { on: boolean; label: string; tone?: "bad" }) {
  return (
    <span
      className={cn(
        "flex items-center gap-1.5 whitespace-nowrap text-xs",
        tone === "bad" ? "text-bad-ink" : on ? "text-ok-ink" : "text-muted",
      )}
    >
      <span
        className={cn("h-2 w-2 rounded-full", tone === "bad" ? "bg-bad-ink" : on ? "bg-ok-ink" : "bg-muted/60")}
        aria-hidden="true"
      />
      {label}
    </span>
  );
}

export function LastRead({ iso, now }: { iso: string | null; now: string }) {
  if (!iso) return null;
  return (
    <span title={formatDateTime(iso)}>
      Last read <span className="num">{timeAgo(iso, now)}</span>
    </span>
  );
}

/** One source with no button yet: its state, when it was last read, and how to connect it. */
export function SourceRow({ s, now }: { s: ConnectSource; now: string }) {
  const copy = copyFor(s.id);
  const on = s.connected;
  const live = s.how === "live";
  return (
    <div className="flex items-start gap-3.5 px-4 py-3.5">
      <Chip id={s.id} />
      <div className="min-w-0 flex-1 pt-0.5">
        <div className="flex items-center justify-between gap-3">
          <span className="min-w-0 truncate font-medium text-ink">
            {copy.label}
            {s.detail && <span className="num ml-2 text-xs font-normal text-muted">{s.detail}</span>}
          </span>
          <StatePill on={on} label={live ? (on ? "Connected" : "Not connected") : on ? "Imported" : "Not yet"} />
        </div>
        <div className="mt-1 space-y-1 text-sm leading-relaxed text-muted">
          {s.lastRead && (
            <div>
              <LastRead iso={s.lastRead} now={now} />
            </div>
          )}
          {!on && copy.how && (
            <div>
              {copy.how} {copy.command && <Command>{copy.command}</Command>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function PrimaryButton({
  children,
  onClick,
  disabled = false,
  type = "button",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-1.5 rounded-full bg-accent px-3.5 py-1.5 text-sm font-medium whitespace-nowrap text-accent-ink transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  );
}

/**
 * Where a sign-in or read stands: what's happening while it runs (with a way to stop it), or
 * how it ended. `done` says it in the page's words; a failure shows the command's own line.
 */
export function JobLine({
  job,
  running,
  done,
  onCancel,
}: {
  job: ConnectJob | null;
  running: React.ReactNode;
  done: React.ReactNode;
  onCancel: () => void;
}) {
  if (!job) return null;
  if (job.state === "running") {
    return (
      <div className="flex items-start gap-2.5 rounded-xl border border-accent/30 bg-accent/5 px-3.5 py-2.5 text-sm" role="status">
        <LoaderCircle size={16} className="mt-0.5 flex-shrink-0 animate-spin text-accent" aria-hidden="true" />
        <span className="min-w-0 flex-1 leading-relaxed text-ink">{running}</span>
        <button onClick={onCancel} className="flex-shrink-0 text-muted underline-offset-2 hover:text-ink hover:underline">
          Cancel
        </button>
      </div>
    );
  }
  const ok = job.state === "done";
  const stopped = job.state === "stopped";
  const Icon = ok ? Check : X;
  return (
    <div
      className={cn(
        "flex items-start gap-2.5 rounded-xl border px-3.5 py-2.5 text-sm",
        ok
          ? "border-ok-line bg-ok-bg text-ok-ink"
          : stopped
            ? "border-line-strong bg-surface-2 text-muted"
            : "border-bad-line bg-bad-bg text-bad-ink",
      )}
      role={ok || stopped ? "status" : "alert"}
    >
      <Icon size={16} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1 break-words leading-relaxed">
        {ok ? done : stopped ? "Stopped." : job.message || "It didn't work."}
      </span>
    </div>
  );
}
