"use client";

import { ExternalLink, LogIn, RefreshCw } from "lucide-react";
import { useState } from "react";

import { isAddress } from "@/lib/actions";
import type { ConnectJob, ConnectSource } from "@/lib/types";

import { Chip, copyFor, JobLine, LastRead, PrimaryButton, StatePill } from "./parts";

const GOOGLE_STEPS = "https://github.com/mindemory/proxenos/blob/main/docs/data_sources.md#email";
const FULL_DISK_ACCESS = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles";
const ACCOUNT_NAME = /^[A-Za-z0-9_]{1,32}$/;

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
