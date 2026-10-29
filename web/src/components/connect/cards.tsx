"use client";

import { ChevronRight, ExternalLink, LogIn, RefreshCw, Save, Smartphone } from "lucide-react";
import { useState } from "react";

import { Command } from "@/components/EmptyState";
import { isAddress } from "@/lib/actions";
import type { ConnectJob, ConnectSource, PhoneInfo } from "@/lib/types";

import { QrCode } from "./QrCode";
import { Chip, CopyBox, copyFor, JobLine, LastRead, PrimaryButton, Steps, StatePill } from "./parts";

const GOOGLE_STEPS = "https://github.com/mindemory/proxenos/blob/main/docs/data_sources.md#email";
const FULL_DISK_ACCESS = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles";
const ACCOUNT_NAME = /^[A-Za-z0-9_]{1,32}$/;
/** A Slack workspace's name as it appears before .slack.com. */
const WORKSPACE_NAME = /^[a-z0-9][a-z0-9-]{0,62}$/;

function CardHead({ s, pill }: { s: ConnectSource; pill: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3.5">
      <Chip id={s.id} />
      <div className="min-w-0 flex-1 pt-0.5">
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-medium text-ink">{copyFor(s.id).label}</h3>
          {pill}
        </div>
        <p className="mt-1 text-sm leading-relaxed text-muted">{copyFor(s.id).how}</p>
      </div>
    </div>
  );
}

const inputClass =
  "w-full rounded-lg border border-line-strong bg-bg px-2.5 py-1.5 text-sm text-ink placeholder:text-muted/80 focus:border-accent/60 focus:outline-none";

/** Steps that stay out of the way once a source works, and are open while it doesn't. */
function Setup({ open, children }: { open: boolean; children: React.ReactNode }) {
  return (
    <details open={open} className="group">
      <summary className="inline-flex cursor-pointer select-none list-none items-center gap-1 rounded text-sm text-muted hover:text-ink [&::-webkit-details-marker]:hidden">
        <ChevronRight size={14} className="transition-transform group-open:rotate-90" aria-hidden="true" />
        How to set it up
      </summary>
      <div className="mt-2.5 space-y-3">{children}</div>
    </details>
  );
}

/** When a source that's read on every sync was last read. */
function SyncLine({ s, now }: { s: ConnectSource; now: string }) {
  return (
    <p className="text-sm text-muted">
      {s.lastRead ? (
        <>
          <LastRead iso={s.lastRead} now={now} />. It&apos;s read again on every sync.
        </>
      ) : (
        "Not read yet. It's read on the next sync."
      )}
    </p>
  );
}

/** Gmail: the accounts signed in, and a Google sign-in for another (or the same one again). */
export function GmailCard({
  s,
  now,
  job,
  onSignIn,
  onCancel,
}: {
  s: ConnectSource;
  now: string;
  job: ConnectJob | null;
  onSignIn: (name: string, address: string) => Promise<string | null>;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const noClient = s.problem === "no_google_client";
  const busy = job?.state === "running";

  const signIn = (n: string, a: string) => {
    setFormError(null);
    onSignIn(n, a).then(setFormError);
  };
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!ACCOUNT_NAME.test(name)) setFormError("Name the account with letters, digits or _, e.g. personal.");
    else if (!isAddress(address.trim())) setFormError("That isn't an email address.");
    else signIn(name, address.trim());
  };

  return (
    <section className="card space-y-4 p-4 sm:p-5">
      <CardHead s={s} pill={<StatePill on={s.connected} label={s.connected ? "Connected" : "Not connected"} />} />

      {s.accounts.length > 0 && (
        <ul className="divide-y divide-line rounded-xl border border-line">
          {s.accounts.map((a) => (
            <li key={a.name} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5 px-3.5 py-2.5 text-sm">
              <div className="min-w-0">
                <div className="truncate text-ink">{a.address}</div>
                <div className="text-xs text-muted">
                  {a.signIn === "google" ? "Google sign-in" : "App password"} · <span className="num">{a.name}</span>
                  {a.lastRead ? (
                    <>
                      {" · "}
                      <LastRead iso={a.lastRead} now={now} />
                    </>
                  ) : (
                    " · read on the next sync"
                  )}
                </div>
              </div>
              {a.signIn === "google" && (
                <button
                  onClick={() => signIn(a.name, a.address)}
                  disabled={busy || noClient}
                  className="inline-flex items-center gap-1.5 rounded-full border border-line-strong px-3 py-1 text-[13px] text-muted transition-colors hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <RefreshCw size={13} aria-hidden="true" />
                  Sign in again
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={submit} className="space-y-2.5">
        <p className="smallcaps text-faint">{s.accounts.length ? "Add an account" : "Sign in"}</p>
        <div className="grid gap-2.5 sm:grid-cols-[minmax(0,9rem)_minmax(0,1fr)_auto] sm:items-end">
          <label className="block space-y-1">
            <span className="text-xs text-muted">Short name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="personal"
              autoComplete="off"
              spellCheck={false}
              maxLength={32}
              className={inputClass}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-xs text-muted">Address</span>
            <input
              type="email"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="you@gmail.com"
              autoComplete="email"
              spellCheck={false}
              className={inputClass}
            />
          </label>
          <PrimaryButton type="submit" disabled={busy || noClient}>
            <LogIn size={14} aria-hidden="true" />
            Sign in with Google
          </PrimaryButton>
        </div>
        {formError && (
          <p className="text-sm text-bad-ink" role="alert">
            {formError}
          </p>
        )}
      </form>

      {noClient && (
        <p className="rounded-xl border border-warn-line bg-warn-bg px-3.5 py-2.5 text-sm leading-relaxed text-warn-ink">
          Sign-in needs a Google OAuth client first. In Google Cloud, make a <em>Desktop app</em> client with the Gmail API
          on, put its ID and secret in .env as GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, then reload this page.{" "}
          <a href={GOOGLE_STEPS} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 underline underline-offset-2">
            The steps
            <ExternalLink size={12} aria-hidden="true" />
          </a>
        </p>
      )}

      <JobLine
        job={job}
        onCancel={onCancel}
        running={
          <>
            Waiting for you in the browser tab that just opened: sign in as {job?.account} and allow access to your mail.
            Proxenos only reads it.
          </>
        }
        done={<>Signed in as {job?.account}. Proxenos reads it on every sync.</>}
      />
    </section>
  );
}

/** "12 added, 3 updated" from the ingester's summary line, in the page's words. */
function readSummary(message: string): string {
  const count = (word: string) => Number(message.match(new RegExp(`(\\d+) ${word}`))?.[1] ?? NaN);
  const added = count("added");
  const updated = count("updated");
  if (Number.isNaN(added)) return message || "Read.";
  const parts = [`${added.toLocaleString()} new ${added === 1 ? "message" : "messages"}`];
  if (updated > 0) parts.push(`${updated.toLocaleString()} changed`);
  return `Read: ${parts.join(", ")}.`;
}

/** WhatsApp: whether its store can be read, and a button that reads it now. */
export function WhatsAppCard({
  s,
  now,
  job,
  onRead,
  onCancel,
}: {
  s: ConnectSource;
  now: string;
  job: ConnectJob | null;
  onRead: () => void;
  onCancel: () => void;
}) {
  const pill =
    s.problem === "blocked" ? (
      <StatePill on={false} label="Blocked by macOS" tone="bad" />
    ) : s.problem === "missing" ? (
      <StatePill on={false} label="Not on this Mac" />
    ) : (
      <StatePill on={s.connected} label={s.connected ? "Connected" : "Not connected"} />
    );

  return (
    <section className="card space-y-4 p-4 sm:p-5">
      <CardHead s={s} pill={pill} />

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <PrimaryButton onClick={onRead} disabled={job?.state === "running" || s.problem === "missing"}>
          <RefreshCw size={14} aria-hidden="true" />
          Read WhatsApp now
        </PrimaryButton>
        <span className="text-sm text-muted">
          {s.lastRead ? <LastRead iso={s.lastRead} now={now} /> : "Not read yet"}
        </span>
      </div>

      {s.problem === "blocked" && (
        <p className="rounded-xl border border-warn-line bg-warn-bg px-3.5 py-2.5 text-sm leading-relaxed text-warn-ink">
          macOS is keeping Proxenos out of WhatsApp&apos;s store. In System Settings, Privacy &amp; Security, Full Disk
          Access, allow the app that runs Proxenos (Terminal, if you started it there), then read again.{" "}
          <a href={FULL_DISK_ACCESS} className="inline-flex items-center gap-1 underline underline-offset-2">
            Open Full Disk Access
            <ExternalLink size={12} aria-hidden="true" />
          </a>
        </p>
      )}
      {s.problem === "missing" && (
        <p className="text-sm leading-relaxed text-muted">
          WhatsApp for Mac isn&apos;t signed in on this computer. Install it from the App Store, sign in with your phone, then
          come back.
        </p>
      )}

      <JobLine
        job={job}
        onCancel={onCancel}
        running="Reading WhatsApp. The first read can take a few minutes."
        done={job ? readSummary(job.message) : null}
      />
    </section>
  );
}

/**
 * Apple Mail: whether it has been read, and what to set up so it can be. It's read on every
 * sync, so there's no button; macOS decides whether this Python may open Mail's files.
 */
export function AppleMailCard({ s, now }: { s: ConnectSource; now: string }) {
  return (
    <section className="card space-y-4 p-4 sm:p-5">
      <CardHead s={s} pill={<StatePill on={s.connected} label={s.connected ? "Connected" : "Not connected"} />} />
      <SyncLine s={s} now={now} />
      <Setup open={!s.connected}>
        <Steps>
          <li>Add each email account in System Settings, Internet Accounts, with Mail turned on for it.</li>
          <li>Keep Mail open: in the Dock, right-click Mail, then Options, Open at Login.</li>
          <li className="space-y-2">
            <p>
              Give {s.detail ? "this Python" : "the Python that runs Proxenos"} Full Disk Access: System Settings, Privacy &amp;
              Security, Full Disk Access, press +, press Cmd-Shift-G and paste{s.detail ? " its path" : " the path"}.
            </p>
            {s.detail && <CopyBox text={s.detail} what="Path" />}
            <a href={FULL_DISK_ACCESS} className="inline-flex items-center gap-1 underline underline-offset-2">
              Open Full Disk Access
              <ExternalLink size={12} aria-hidden="true" />
            </a>
          </li>
        </Steps>
      </Setup>
    </section>
  );
}

/** "https://acme.slack.com/", "Acme.slack.com" or "acme", as the name slackdump wants; null if it isn't one. */
function workspaceName(text: string): string | null {
  const name = text
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\//, "")
    .replace(/\.slack\.com.*$/, "");
  return WORKSPACE_NAME.test(name) ? name : null;
}

/** Slack: the workspaces signed in, and the Terminal command that adds another. */
export function SlackCard({ s, now }: { s: ConnectSource; now: string }) {
  const [text, setText] = useState("");
  const name = workspaceName(text);
  const command = `proxenos auth slackdump ${name ?? "NAME"}`;

  return (
    <section className="card space-y-4 p-4 sm:p-5">
      <CardHead s={s} pill={<StatePill on={s.connected} label={s.connected ? "Connected" : "Not connected"} />} />

      {s.workspaces.length > 0 ? (
        <ul className="flex flex-wrap gap-2">
          {s.workspaces.map((w) => (
            <li key={w} className="rounded-full border border-line-strong px-3 py-1 text-sm text-ink">
              {w}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">No workspaces yet.</p>
      )}
      {s.lastRead && (
        <p className="text-sm text-muted">
          <LastRead iso={s.lastRead} now={now} />
        </p>
      )}

      <div className="space-y-2.5">
        <p className="smallcaps text-faint">{s.workspaces.length ? "Add a workspace" : "Add your first"}</p>
        <label className="block space-y-1 sm:max-w-xs">
          <span className="text-xs text-muted">Workspace name, the part before .slack.com</span>
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="acme"
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            maxLength={100}
            className={inputClass}
          />
        </label>
        {text.trim() && !name && (
          <p className="text-sm text-bad-ink" role="alert">
            That isn&apos;t a workspace name. Use letters, digits and dashes, like acme.
          </p>
        )}
        <p className="text-sm leading-relaxed text-muted">Run this in Terminal and follow what it asks, then reload this page.</p>
        <Command block>{command}</Command>
      </div>
    </section>
  );
}

/** A job's line in sentence case: "saved; Beeper has 2 accounts" reads as "Saved; Beeper has 2 accounts". */
function sentence(line: string): string {
  return line.charAt(0).toUpperCase() + line.slice(1);
}

/**
 * Beeper: the steps that make its token, and a place to paste it. The token is handed to the
 * server for the one command that saves it; it isn't kept here, shown again or put in the URL.
 */
export function BeeperCard({
  s,
  now,
  job,
  onSave,
  onCancel,
}: {
  s: ConnectSource;
  now: string;
  job: ConnectJob | null;
  onSave: (token: string) => Promise<string | null>;
  onCancel: () => void;
}) {
  const [token, setToken] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const busy = job?.state === "running";

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!token.trim()) {
      setFormError("Paste the token from Beeper first.");
      return;
    }
    setFormError(null);
    onSave(token).then((why) => {
      setFormError(why);
      if (!why) setToken("");
    });
  };

  return (
    <section className="card space-y-4 p-4 sm:p-5">
      <CardHead
        s={s}
        pill={<StatePill on={s.connected} label={s.connected ? "Connected" : s.problem === "no_token" ? "No token" : "Not connected"} />}
      />
      <SyncLine s={s} now={now} />

      <Setup open={!s.connected}>
        <Steps>
          <li>Keep Beeper Desktop open, with Instagram, Messenger, X or LinkedIn added to it.</li>
          <li>In Beeper, open Settings, Developers, and turn on the Desktop API.</li>
          <li>Still in Settings, open Integrations, press + next to Approved connections, and create a token.</li>
          <li>Paste the token below and press Save.</li>
        </Steps>
      </Setup>

      <form onSubmit={submit} className="space-y-2.5">
        <p className="smallcaps text-faint">{s.connected ? "Replace the token" : "Save the token"}</p>
        <div className="grid gap-2.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
          <label className="block space-y-1">
            <span className="text-xs text-muted">Token</span>
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="Paste it here"
              autoComplete="off"
              autoCapitalize="off"
              spellCheck={false}
              data-1p-ignore
              data-lpignore="true"
              className={inputClass}
            />
          </label>
          <PrimaryButton type="submit" disabled={busy}>
            <Save size={14} aria-hidden="true" />
            Save
          </PrimaryButton>
        </div>
        {formError && (
          <p className="text-sm text-bad-ink" role="alert">
            {formError}
          </p>
        )}
      </form>

      <JobLine
        job={job}
        onCancel={onCancel}
        running="Checking the token with Beeper."
        done={job?.message ? sentence(job.message) : "Token saved."}
      />
    </section>
  );
}

/** Your phone: the address it opens, a code to scan, and the steps that put the app on it. */
export function PhoneCard({ phone }: { phone: PhoneInfo }) {
  const { address, login } = phone;
  return (
    <section className="card space-y-4 p-4 sm:p-5">
      <div className="flex items-start gap-3.5">
        <span
          className="inline-flex h-[38px] w-[38px] flex-shrink-0 items-center justify-center rounded-lg border border-accent/25 bg-accent/10 text-accent"
          aria-hidden="true"
        >
          <Smartphone size={18} />
        </span>
        <div className="min-w-0 flex-1 pt-0.5">
          <div className="flex items-center justify-between gap-3">
            <h3 className="font-medium text-ink">Your phone</h3>
            <StatePill on={!!address} label={address ? "Ready" : "Not set up"} />
          </div>
          <p className="mt-1 text-sm leading-relaxed text-muted">
            Open Proxenos as an app on your phone. It goes over your private Tailscale network and answers only your own login.
          </p>
        </div>
      </div>

      {address ? (
        <div className="grid gap-5 sm:grid-cols-[auto_minmax(0,1fr)] sm:items-start">
          <QrCode value={address} />
          <div className="min-w-0 space-y-3">
            <a
              href={address}
              target="_blank"
              rel="noreferrer"
              className="num inline-flex max-w-full items-start gap-1.5 break-all text-sm text-accent underline underline-offset-2"
            >
              {address}
              <ExternalLink size={12} className="mt-1 flex-shrink-0" aria-hidden="true" />
            </a>
            <Steps>
              <li>
                Install Tailscale on your phone and sign in as{" "}
                {login ? <span className="break-words text-ink">{login}</span> : "the same account as on this Mac"}.
              </li>
              <li>In Chrome on your phone, open that address, or scan the code.</li>
              <li>Tap the ⋮ menu, then Install app (or Add to home screen).</li>
            </Steps>
          </div>
        </div>
      ) : (
        <p className="text-sm leading-relaxed text-muted">
          Install Tailscale on this Mac and on your phone, signed in to the same account. Then run <Command>proxenos phone</Command>{" "}
          in Terminal. Its address and a QR code show up here.
        </p>
      )}
    </section>
  );
}
