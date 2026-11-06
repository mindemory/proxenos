"use client";

import { Check, Copy, ExternalLink, LoaderCircle, X } from "lucide-react";
import { useEffect, useState } from "react";

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
  /** What to say in the desktop app in place of `how`, where there's no terminal: its own steps, or that it needs one. */
  app?: string;
  command?: string;
}

/** What the desktop app says of a source that can only be set up from a terminal. */
const NEEDS_TERMINAL = "This one can't be set up from the app. It needs a terminal.";

/** Every source the page lists: its name, and how to connect it for now. */
export const SOURCE_COPY: Record<string, SourceCopy> = {
  applemail: {
    label: "Apple Mail",
    kind: "email",
    how: "Email from every account in the Mail app on this Mac. Nothing to sign in to here.",
  },
  gmail: { label: "Gmail", kind: "email", how: "Your Gmail, read again on every sync. Sign in once for each account." },
  microsoft: {
    label: "Microsoft 365 and Outlook",
    kind: "email",
    how: "Your Outlook or Microsoft 365 mail and calendar, read again on every sync. Sign in once for each account.",
  },
  gcalendar: {
    label: "Google Calendar",
    kind: "calendar",
    how: "Your calendar, from a year back to two months ahead. Proxenos can only read it. Sign in once for each account.",
  },
  gdocs: {
    label: "Google Docs",
    kind: "drive",
    how: "A paper's manuscript as a Google Doc in your own Drive, to edit, comment on and share with co-authors. Its changes come back as a step for you to accept. A doc is made only when you press Open in Google Docs on a manuscript. Proxenos can see only the files it makes.",
  },
  whatsapp: { label: "WhatsApp", how: "Your messages and groups, read from the WhatsApp app on this Mac." },
  slack: {
    label: "Slack",
    how: "Your Slack messages, one workspace at a time. Proxenos uses a free program called slackdump to read them, signed in as you.",
  },
  beeper: {
    label: "Beeper",
    how: "Instagram, Messenger, X and LinkedIn chats, read through Beeper Desktop. Beeper is free for up to 5 accounts, so add only those networks there. Proxenos reads WhatsApp, Slack and email itself.",
  },
  strava: {
    label: "Strava",
    how: "Needs a Strava app's ID and secret in .env. Then sign in once. From a terminal:",
    app: NEEDS_TERMINAL,
    command: "proxenos auth strava",
  },
  bluesky: {
    label: "Bluesky",
    how: "Your public posts. Put your handle in .env as PROXENOS_BLUESKY_HANDLE.",
    app: NEEDS_TERMINAL,
  },
  mentions: {
    label: "Papers and mentions",
    how: "News about you, and your papers. Put your full name in .env as PROXENOS_FULL_NAME.",
    app: NEEDS_TERMINAL,
  },
  linkedin: { label: "LinkedIn", how: "On LinkedIn: Settings, Data privacy, Get a copy of your data." },
  twitter: { label: "X", how: "On X: Settings, Your account, Download an archive of your data." },
  instagram: {
    label: "Instagram",
    how: "In Accounts Center: Your information and permissions, Download your information. Choose JSON, all time, with messages.",
  },
  facebook: {
    label: "Facebook",
    how: "In Accounts Center: Your information and permissions, Download your information. Choose JSON, all time, with messages.",
  },
  threads: { label: "Threads", how: "The same Download your information page, with Threads picked." },
  calendar: { label: "Calendar export", how: "From Google Takeout, pick Calendar. Or use any calendar's .ics export." },
  drive: { label: "Google Drive", how: "From Google Takeout, pick Drive." },
  photos: { label: "Google Photos", how: "From Google Takeout, pick Google Photos. Proxenos reads only dates, places and people." },
  keep: { label: "Google Keep", how: "From Google Takeout, pick Keep." },
  gtasks: { label: "Google Tasks", how: "From Google Takeout, pick Tasks." },
  youtube: { label: "YouTube", how: "From Google Takeout, pick YouTube and YouTube Music. Choose JSON if it's offered." },
  chrome: { label: "Chrome history", how: "From Google Takeout, pick Chrome." },
  chatgpt: { label: "ChatGPT", how: "On ChatGPT: Settings, Data controls, Export data. The email it sends has a zip." },
  claude: { label: "Claude", how: "On claude.ai: Settings, Privacy, Export data. The email it sends has a zip." },
  email: {
    label: "Other email",
    kind: "email",
    how: "An mbox file, from Takeout's Mail or your mail program. From a terminal:",
    app: NEEDS_TERMINAL,
    command: "proxenos ingest email --account NAME --mbox PATH",
  },
  spotify: {
    label: "Spotify",
    how: "Live: make an app at developer.spotify.com (Web API, redirect URI http://127.0.0.1:8723/callback), save its Client ID in Settings as SPOTIFY_CLIENT_ID, then sign in once from a terminal. Each sync then reads your latest plays. Your whole history: in Spotify, Account, Privacy settings, ask for Extended streaming history. It can take up to 30 days.",
    app: "Your whole history: in Spotify, open Account, Privacy settings, and ask for Extended streaming history. It can take up to 30 days. When it arrives, unzip it and pick that folder in Settings, under Spotify export. The live feed needs a terminal.",
    command: "proxenos auth spotify",
  },
  letterboxd: { label: "Letterboxd", how: "On Letterboxd: Settings, Data, Export your data." },
  notes: {
    label: "Notes and PDFs",
    how: "A Notion export, an Obsidian vault or a folder of PDFs. From a terminal:",
    app: NEEDS_TERMINAL,
    command: "proxenos ingest notes --export DIR",
  },
  website: {
    label: "Your website",
    how: "Its local git folder, set as PROXENOS_WEBSITE_REPO in .env.",
    app: "In Settings, under Folders, type its folder next to Your website, then press Save folders.",
  },
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

/** The Full Disk Access pane of System Settings, which macOS lets a link open. */
export const FULL_DISK_ACCESS = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles";

/**
 * Full Disk Access, which Mail's and WhatsApp's folders need: a button that opens the pane, what to
 * do there, and a green line once it's on. `onCheck` looks again whenever this window gets focus
 * back, which is when someone returns from Settings. Nothing shows off a Mac (`allowed` null).
 */
export function FullDiskAccess({ allowed, inApp, onCheck }: { allowed: boolean | null; inApp: boolean; onCheck: () => void }) {
  useEffect(() => {
    window.addEventListener("focus", onCheck);
    return () => window.removeEventListener("focus", onCheck);
  }, [onCheck]);
  if (allowed === null) return null;
  if (allowed) {
    return (
      <p className="flex items-center gap-1.5 text-sm text-ok-ink" role="status">
        <Check size={15} aria-hidden="true" />
        {inApp ? "Proxenos" : "This Python"} can read Mail and WhatsApp.
      </p>
    );
  }
  return (
    <div className="space-y-2.5">
      <p className="text-sm leading-relaxed text-muted">
        macOS keeps Mail&apos;s and WhatsApp&apos;s files private until you allow this.
      </p>
      <a
        href={FULL_DISK_ACCESS}
        className="inline-flex items-center gap-1.5 rounded-full bg-accent px-3.5 py-1.5 text-sm font-medium whitespace-nowrap text-accent-ink transition-opacity hover:opacity-90"
      >
        Open Full Disk Access
        <ExternalLink size={13} aria-hidden="true" />
      </a>
      <Steps>
        <li>
          Press <strong>Open Full Disk Access</strong>. System Settings opens at <strong>Privacy &amp; Security → Full Disk Access</strong>.
        </li>
        {inApp ? (
          <li>
            Turn on the switch beside <strong>Proxenos</strong>. If it isn&apos;t listed, press <strong>+</strong> and choose Proxenos
            in Applications. macOS may ask for your password.
          </li>
        ) : (
          <li>
            Turn on the switch beside the app that runs Proxenos (Terminal, if you started it there). If it isn&apos;t listed, press{" "}
            <strong>+</strong> and choose it.
          </li>
        )}
        <li>If macOS offers <strong>Quit &amp; Reopen</strong>, choose it. Then come back here.</li>
      </Steps>
      <p className="text-xs leading-relaxed text-muted">
        You&apos;ll see &quot;{inApp ? "Proxenos" : "This Python"} can read Mail and WhatsApp&quot; here when it works. This page checks again
        by itself. Still blocked? {inApp ? "Choose Quit Proxenos from its menu-bar icon, open Proxenos again" : "Quit and start Proxenos again"}.
      </p>
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
export function SourceRow({ s, now, inApp = false }: { s: ConnectSource; now: string; inApp?: boolean }) {
  const copy = copyFor(s.id);
  const on = s.connected;
  const live = s.how === "live";
  return (
    <div className="flex items-start gap-3.5 px-4 py-3.5">
      <Chip id={s.id} />
      <div className="min-w-0 flex-1 pt-0.5">
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
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
          {!on && (inApp ? (copy.app ?? copy.how) : copy.how) && (
            <div>
              {inApp ? (copy.app ?? copy.how) : copy.how}
              {!inApp && copy.command && (
                <>
                  {" "}
                  <Command>{copy.command}</Command>
                </>
              )}
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
