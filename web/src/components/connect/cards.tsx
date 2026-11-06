"use client";

import { ChevronRight, ExternalLink, LogIn, RefreshCw, Save, Smartphone } from "lucide-react";
import { useState } from "react";

import { Command } from "@/components/EmptyState";
import { GoogleClientFile } from "@/components/setup/parts";
import { isAddress } from "@/lib/actions";
import { postChange } from "@/lib/setupClient";
import type { ConnectJob, ConnectSource, MailAccount, PhoneInfo } from "@/lib/types";

import { QrCode } from "./QrCode";
import { Chip, CopyBox, copyFor, FULL_DISK_ACCESS, FullDiskAccess, JobLine, LastRead, PrimaryButton, Steps, StatePill } from "./parts";

const MAIL_STEPS = "https://github.com/mindemory/proxenos/blob/main/docs/data_sources.md#email";
const CALENDAR_STEPS = "https://github.com/mindemory/proxenos/blob/main/docs/data_sources.md#activity-and-habits";
const DOCS_STEPS = "https://github.com/mindemory/proxenos/blob/main/docs/data_sources.md#a-manuscript-in-google-docs";
const ACCOUNT_NAME = /^[A-Za-z0-9_]{1,32}$/;
/** A Slack workspace's name as it appears before .slack.com. */
const WORKSPACE_NAME = /^[a-z0-9][a-z0-9-]{0,62}$/;

function CardHead({ s, pill }: { s: ConnectSource; pill: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3.5">
      <Chip id={s.id} />
      <div className="min-w-0 flex-1 pt-0.5">
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
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

const SIGN_IN_LABELS: Record<MailAccount["signIn"], string> = {
  google: "Google sign-in",
  microsoft: "Microsoft sign-in",
  app_password: "App password",
};

/** What a sign-in card says: its button, an example address, and what's asked for and read. */
interface SignInCopy {
  button: string;
  placeholder: string;
  /** The source's problem when its sign-in client isn't set up yet. */
  noClientProblem: string;
  noClient: React.ReactNode;
  /** In the desktop app, where there's no .env to put it in. */
  noClientInApp?: React.ReactNode;
  /** What the consent page asks to read, and what Proxenos reads after, for the running and done lines. */
  asks: string;
  reads: string;
  /** Beside an account that hasn't been read yet, when that isn't the next sync's job. */
  unread?: string;
  /** Google's sign-in: it can load a client file, and its consent screen warns the project is unverified. */
  google?: boolean;
}

function StepsLink({ href }: { href: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 underline underline-offset-2">
      The steps
      <ExternalLink size={12} aria-hidden="true" />
    </a>
  );
}

const GMAIL_COPY: SignInCopy = {
  button: "Sign in with Google",
  placeholder: "you@gmail.com",
  noClientProblem: "no_google_client",
  google: true,
  noClient: (
    <>
      Sign-in needs a Google sign-in client first (a code pair from Google that lets Proxenos ask you to sign in). In Google Cloud,
      make a <em>Desktop app</em> client with the Gmail API turned on. Put its ID and secret in .env as GOOGLE_CLIENT_ID and
      GOOGLE_CLIENT_SECRET, or load the file Google gives you below, then reload this page. <StepsLink href={MAIL_STEPS} />
    </>
  ),
  asks: "allow access to your mail. Proxenos only reads it.",
  reads: "Proxenos reads it on every sync.",
};

const MICROSOFT_COPY: SignInCopy = {
  button: "Sign in with Microsoft",
  placeholder: "you@outlook.com",
  noClientProblem: "no_microsoft_client",
  noClient: (
    <>
      Sign-in needs your own Microsoft app registration first (a free entry that tells Microsoft which app is asking). In the Azure
      portal, open Microsoft Entra ID, then App registrations, and register an app for any organization&apos;s and personal Microsoft
      accounts. Add http://localhost as a <em>Mobile and desktop applications</em> redirect. Put its Application (client) ID in .env as
      MICROSOFT_CLIENT_ID, then reload this page. It needs no secret. <StepsLink href={MAIL_STEPS} />
    </>
  ),
  noClientInApp: (
    <>
      Sign-in needs your own Microsoft app registration first (a free entry that tells Microsoft which app is asking). Follow the
      steps, then open <strong>Settings → Keys and sign-ins</strong>, press <strong>Add</strong> beside{" "}
      <strong>Microsoft sign-in client ID</strong>, paste the Application (client) ID, and press <strong>Save</strong>. Then come
      back here. <StepsLink href={MAIL_STEPS} />
    </>
  ),
  asks: "accept read access to your mail and calendar. Proxenos only reads them.",
  reads: "Proxenos reads its mail and calendar on every sync.",
};

const CALENDAR_COPY: SignInCopy = {
  button: "Sign in with Google",
  placeholder: "you@gmail.com",
  noClientProblem: "no_google_client",
  google: true,
  noClient: (
    <>
      Sign-in needs a Google sign-in client first: the same <em>Desktop app</em> client as Gmail&apos;s, with the Google Calendar
      API turned on in its project. Put its ID and secret in .env as GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, or load the file
      Google gives you below, then reload this page. <StepsLink href={CALENDAR_STEPS} />
    </>
  ),
  asks: "allow read-only access to your calendar.",
  reads: "Proxenos reads its calendar on every sync.",
};

const DOCS_COPY: SignInCopy = {
  button: "Sign in with Google",
  placeholder: "you@gmail.com",
  noClientProblem: "no_google_client",
  google: true,
  noClient: (
    <>
      Sign-in needs a Google sign-in client first: the same <em>Desktop app</em> client as Gmail&apos;s, with the Google Drive API
      turned on in its project. Put its ID and secret in .env as GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, or load the file Google
      gives you below, then reload this page. <StepsLink href={DOCS_STEPS} />
    </>
  ),
  asks: "allow access to only the files Proxenos makes in your Drive.",
  reads: "Pressing Open in Google Docs on a manuscript now makes its doc in that Drive.",
  unread: "used when you open a manuscript in Google Docs",
};

interface SignInProps {
  s: ConnectSource;
  now: string;
  job: ConnectJob | null;
  /** The desktop app: no Google Cloud steps to point at, and a copy built without a client says so. */
  inApp: boolean;
  /** After a Google client file is loaded: read the sources again, so the sign-in button shows. */
  onClient: () => void;
  onSignIn: (name: string, address: string) => Promise<string | null>;
  onCancel: () => void;
}

/** Gmail: the accounts signed in, and a Google sign-in for another (or the same one again). */
export function GmailCard(props: SignInProps) {
  return <SignInCard {...props} copy={GMAIL_COPY} />;
}

/** Microsoft 365 and Outlook.com: mail and calendar through Microsoft's own sign-in, one account at a time. */
export function MicrosoftCard(props: SignInProps) {
  return <SignInCard {...props} copy={MICROSOFT_COPY} />;
}

/** Google Calendar, live: a read-only Google sign-in per account, apart from Gmail's. */
export function GoogleCalendarCard(props: SignInProps) {
  return <SignInCard {...props} copy={CALENDAR_COPY} />;
}

/** Google Docs: a sign-in that sees only the files Proxenos makes, for a manuscript's doc. */
export function GoogleDocsCard(props: SignInProps) {
  return <SignInCard {...props} copy={DOCS_COPY} />;
}

/** A source read through a sign-in: the accounts signed in, and a sign-in for another (or the same one again). */
function SignInCard({ s, now, job, inApp, onClient, onSignIn, onCancel, copy }: SignInProps & { copy: SignInCopy }) {
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const noClient = s.problem === copy.noClientProblem;
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
                  {SIGN_IN_LABELS[a.signIn]} · <span className="num">{a.name}</span>
                  {a.lastRead ? (
                    <>
                      {" · "}
                      <LastRead iso={a.lastRead} now={now} />
                    </>
                  ) : (
                    ` · ${copy.unread ?? "read on the next sync"}`
                  )}
                </div>
              </div>
              {a.signIn !== "app_password" && (
                <button
                  onClick={() => signIn(a.name, a.address)}
                  disabled={busy || noClient}
                  className="inline-flex items-center gap-1.5 rounded-full border border-line-strong px-3 py-1 text-[0.8125rem] text-muted transition-colors hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <RefreshCw size={13} aria-hidden="true" />
                  Sign in again
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {!noClient && (
        <Setup open={!s.connected}>
          <Steps>
            <li>
              Type a short name for the account (like <strong>personal</strong> or <strong>work</strong>) and its email address.
            </li>
            <li>
              Press <strong>{copy.button}</strong>. A tab opens in your browser.
            </li>
            <li>Sign in there as that account.</li>
            {copy.google && (
              <li>
                Google warns that it hasn&apos;t verified Proxenos. That&apos;s because Proxenos hasn&apos;t been through Google&apos;s
                review yet. To go on, press <strong>Advanced</strong>, then <strong>Go to Proxenos (unsafe)</strong>.
              </li>
            )}
            <li>On the next screen, {copy.asks}</li>
          </Steps>
          <p className="text-xs leading-relaxed text-muted">
            You&apos;ll see &quot;Signed in as …&quot; here when it works. If you close the tab before you finish, press Cancel and try
            again.
          </p>
        </Setup>
      )}

      <form onSubmit={submit} className="space-y-2.5">
        <p className="smallcaps text-faint">{s.accounts.length ? "Add an account" : "Sign in"}</p>
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-[minmax(0,9rem)_minmax(0,1fr)_auto] sm:items-end">
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
              placeholder={copy.placeholder}
              autoComplete="email"
              spellCheck={false}
              className={inputClass}
            />
          </label>
          <PrimaryButton type="submit" disabled={busy || noClient}>
            <LogIn size={14} aria-hidden="true" />
            {copy.button}
          </PrimaryButton>
        </div>
        {formError && (
          <p className="text-sm text-bad-ink" role="alert">
            {formError}
          </p>
        )}
      </form>

      {noClient && (
        <div className="space-y-2.5">
          <p className="break-words rounded-xl border border-warn-line bg-warn-bg px-3.5 py-2.5 text-sm leading-relaxed text-warn-ink">
            {copy.google && inApp ? (
              <>
                This copy of Proxenos has no Google sign-in built in. If you made a Google sign-in client of your own, load its file
                below. <StepsLink href={MAIL_STEPS} />
              </>
            ) : inApp && copy.noClientInApp ? (
              copy.noClientInApp
            ) : (
              copy.noClient
            )}
          </p>
          {copy.google && (
            <GoogleClientFile save={(change) => postChange(change).then((r) => (onClient(), r.message ?? "Saved."))} />
          )}
        </div>
      )}

      <JobLine
        job={job}
        onCancel={onCancel}
        running={
          <>
            Waiting for you in the browser tab that just opened. Sign in as {job?.account}, then {copy.asks}
          </>
        }
        done={
          <>
            Signed in as {job?.account}. {copy.reads}
          </>
        }
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
  inApp,
  onRead,
  onCancel,
}: {
  s: ConnectSource;
  now: string;
  job: ConnectJob | null;
  inApp: boolean;
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
        <p className="break-words rounded-xl border border-warn-line bg-warn-bg px-3.5 py-2.5 text-sm leading-relaxed text-warn-ink">
          macOS is keeping {inApp ? "Proxenos" : "this app"} out of WhatsApp&apos;s files. In{" "}
          <strong>System Settings → Privacy &amp; Security → Full Disk Access</strong>, turn on{" "}
          {inApp ? "Proxenos" : "the app that runs Proxenos (Terminal, if you started it there)"}, then press{" "}
          <strong>Read WhatsApp now</strong> again.{" "}
          <a href={FULL_DISK_ACCESS} className="inline-flex items-center gap-1 underline underline-offset-2">
            Open Full Disk Access
            <ExternalLink size={12} aria-hidden="true" />
          </a>
        </p>
      )}
      {s.problem === "missing" && (
        <Steps>
          <li>Install WhatsApp for Mac from the App Store.</li>
          <li>Open it and sign in by scanning its code with your phone.</li>
          <li>
            Come back here and press <strong>Read WhatsApp now</strong>.
          </li>
        </Steps>
      )}
      {s.problem === null && !s.connected && (
        <p className="text-xs leading-relaxed text-muted">
          You&apos;ll see &quot;Read: …new messages&quot; here when it works. The WhatsApp app on a Mac may hold less history than your
          phone.
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
export function AppleMailCard({
  s,
  now,
  inApp,
  fullDiskAccess,
  onCheck,
}: {
  s: ConnectSource;
  now: string;
  inApp: boolean;
  fullDiskAccess: boolean | null;
  onCheck: () => void;
}) {
  return (
    <section className="card space-y-4 p-4 sm:p-5">
      <CardHead s={s} pill={<StatePill on={s.connected} label={s.connected ? "Connected" : "Not connected"} />} />
      <SyncLine s={s} now={now} />
      <Setup open={!s.connected}>
        <Steps>
          <li>
            Open <strong>System Settings → Internet Accounts</strong>. Add each email account, with <strong>Mail</strong> turned on for it.
          </li>
          <li>
            Keep the Mail app open, so it downloads new mail. To open it at every login, right-click Mail in the Dock and choose{" "}
            <strong>Options → Open at Login</strong>.
          </li>
          {inApp ? (
            <li className="space-y-2">
              <p>Let Proxenos read Mail&apos;s folder, with Full Disk Access.</p>
              <FullDiskAccess allowed={fullDiskAccess} inApp onCheck={onCheck} />
            </li>
          ) : (
            <li className="space-y-2">
              <p>
                Let {s.detail ? "this Python" : "the Python that runs Proxenos"} read Mail&apos;s folder, with Full Disk Access. In{" "}
                <strong>System Settings → Privacy &amp; Security → Full Disk Access</strong>, press <strong>+</strong>, press{" "}
                <strong>Cmd-Shift-G</strong> and paste {s.detail ? "its path" : "the path"}.
              </p>
              {s.detail && <CopyBox text={s.detail} what="Path" />}
              <a href={FULL_DISK_ACCESS} className="inline-flex items-center gap-1 underline underline-offset-2">
                Open Full Disk Access
                <ExternalLink size={12} aria-hidden="true" />
              </a>
            </li>
          )}
          <li>
            Wait for the next sync. This card then says when Mail was last read. The first read covers the last 180 days.
          </li>
        </Steps>
        <p className="text-xs leading-relaxed text-muted">
          Proxenos works out which address is yours in each Mail account from the mail you&apos;ve sent, so there&apos;s nothing to type.
          If Mail has no mail yet, let it finish downloading first.
        </p>
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

/**
 * Slack: the workspaces signed in, and a button that signs in to another: slackdump is downloaded
 * the first time (Macs), a browser window opens on Slack's login page, and the last 30 days are
 * saved once the person is in. From source, the Terminal command does the same and stays below.
 */
export function SlackCard({
  s,
  now,
  job,
  inApp,
  onSignIn,
  onCancel,
}: {
  s: ConnectSource;
  now: string;
  job: ConnectJob | null;
  inApp: boolean;
  onSignIn: (workspace: string, google: boolean) => Promise<string | null>;
  onCancel: () => void;
}) {
  const [text, setText] = useState("");
  const [google, setGoogle] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const name = workspaceName(text);
  const command = `proxenos auth slackdump ${name ?? "NAME"}${google ? " --google" : ""}`;
  const busy = job?.state === "running";
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name) setFormError("That isn't a workspace name. Use letters, digits and dashes, like acme.");
    else {
      setFormError(null);
      onSignIn(name, google).then(setFormError);
    }
  };

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

      <Setup open={!s.connected}>
        <Steps>
          <li>
            Type the workspace name: the part of your Slack address before .slack.com (<strong>acme</strong> for acme.slack.com).
          </li>
          <li>
            If you sign in to Slack with Google, tick <strong>I sign in to Slack with Google</strong>.
          </li>
          <li>
            Press <strong>Sign in to Slack</strong>.
            {inApp && " The first time, Proxenos downloads slackdump, the free program that reads Slack, from its GitHub page."}
          </li>
          <li>
            Sign in in the window that opens, on Slack&apos;s own login page, as you usually do. With Google, it opens in your own browser
            (Chrome or Firefox) instead.
          </li>
        </Steps>
        <p className="text-xs leading-relaxed text-muted">
          You&apos;ll see &quot;Signed in to …&quot; here when it works. Proxenos then saves your last 30 days, without attachments, and
          reads new messages on every sync. If it can&apos;t open your browser, quit Chrome and press the button again.
        </p>
      </Setup>

      <form onSubmit={submit} className="space-y-2.5">
        <p className="smallcaps text-faint">{s.workspaces.length ? "Add a workspace" : "Add your first"}</p>
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-[minmax(0,16rem)_auto] sm:items-end">
          <label className="block space-y-1">
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
          <PrimaryButton type="submit" disabled={busy}>
            <LogIn size={14} aria-hidden="true" />
            Sign in to Slack
          </PrimaryButton>
        </div>
        <label className="flex items-center gap-2 text-sm text-muted">
          <input type="checkbox" checked={google} onChange={(e) => setGoogle(e.target.checked)} className="accent-[var(--c-accent)]" />
          I sign in to Slack with Google
        </label>
        {(formError || (text.trim() && !name)) && (
          <p className="text-sm text-bad-ink" role="alert">
            {formError ?? "That isn't a workspace name. Use letters, digits and dashes, like acme."}
          </p>
        )}
      </form>
      <JobLine
        job={job}
        onCancel={onCancel}
        running={job?.message || "Starting…"}
        done={`Signed in to ${job?.account ?? "Slack"}. ${job?.message ?? ""}`}
      />
      {!inApp && (
        <div className="space-y-1.5">
          <p className="text-xs leading-relaxed text-faint">From a terminal (it asks how to sign in; follow it), then reload this page:</p>
          <Command block>{command}</Command>
        </div>
      )}
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
          <li>Open Beeper Desktop and keep it open. Add Instagram, Messenger, X or LinkedIn to it.</li>
          <li>
            In Beeper, open <strong>Settings → Developers</strong> and turn on the <strong>Desktop API</strong>.
          </li>
          <li>
            Still in Settings, open <strong>Integrations</strong>. Press <strong>+</strong> next to <strong>Approved connections</strong>{" "}
            and create a token. A token is a long code that lets Proxenos read Beeper.
          </li>
          <li>
            Paste the token below and press <strong>Save</strong>.
          </li>
        </Steps>
        <p className="text-xs leading-relaxed text-muted">
          You&apos;ll see &quot;Saved; Beeper has …&quot; here when it works. If it can&apos;t reach Beeper, check that Beeper Desktop is open and the
          Desktop API is on.
        </p>
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
export function PhoneCard({ phone, inApp = false }: { phone: PhoneInfo; inApp?: boolean }) {
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
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
            <h3 className="font-medium text-ink">Your phone</h3>
            <StatePill on={!!address} label={address ? "Ready" : "Not set up"} />
          </div>
          <p className="mt-1 text-sm leading-relaxed text-muted">
            Open Proxenos as an app on your phone. It goes over your own private network, made with Tailscale (a free app), and
            answers only your own login.
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
              <li>
                Tap the <strong>⋮</strong> menu, then <strong>Install app</strong> (or <strong>Add to home screen</strong>).
              </li>
            </Steps>
            <p className="text-xs leading-relaxed text-muted">
              You&apos;ll see Proxenos as an app on your home screen. If the address doesn&apos;t open, check that Tailscale is on, on
              both the phone and this Mac.
            </p>
          </div>
        </div>
      ) : (
        <p className="text-sm leading-relaxed text-muted">
          {inApp ? (
            "Turning on the phone link needs a terminal, so it isn't available in the app."
          ) : (
            <>
              Install Tailscale on this Mac and on your phone, signed in to the same account. Then, from a terminal, run{" "}
              <Command>proxenos phone</Command>. Its address and a QR code show up here.
            </>
          )}
        </p>
      )}
    </section>
  );
}
