"use client";

import { BellRing, KeyRound, Save, SlidersHorizontal, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PrimaryButton, StatePill } from "@/components/connect/parts";
import { ErrorBanner } from "@/components/EmptyState";
import { Compare } from "@/components/views/Compare";
import { ReadingControls, VoiceControls } from "@/components/reading/ReadingControls";
import {
  type Apply,
  CloudWarning,
  Field,
  inputClass,
  ModelChoice,
  NOT_A_LOGIN,
  originLabel,
  type Said,
  SaidLine,
  secretLabel,
  useChange,
} from "@/components/setup/parts";
import { StatusSkeleton } from "@/components/Skeleton";
import { cloudFor, useSetup } from "@/lib/setupClient";
import type { NoticeTest, SecretState, SettingKey, SettingValue, SetupStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { JSON_HEADERS } from "@/lib/headers";

/** The secrets phone notices use, shown with them rather than with the keys and sign-ins. */
const NOTICE_SECRETS = ["NTFY_TOPIC", "NTFY_TOKEN"];

/** The key a lookup can search with, shown with the other lookup settings. */
const LOOKUP_SECRETS = ["BRAVE_SEARCH_KEY"];

const LOOKUP_SETTINGS: { key: SettingKey; label: string; hint: string; placeholder: string }[] = [
  {
    key: "searxng_url",
    label: "Your SearXNG",
    hint: "Searches go there when it's set, with json among its search formats. Empty: Brave Search with a key below, else DuckDuckGo.",
    placeholder: "http://127.0.0.1:8888",
  },
  {
    key: "lookup",
    label: "Looking people up",
    hint: "off to never look anyone up on the web; empty or on to look.",
    placeholder: "on",
  },
];

const NOTICE_SETTINGS: { key: SettingKey; label: string; hint: string; placeholder: string }[] = [
  {
    key: "ntfy_server",
    label: "Server",
    hint: "Empty for ntfy.sh. Your own ntfy server's address, if you run one.",
    placeholder: "https://ntfy.sh",
  },
  {
    key: "quiet_hours",
    label: "Quiet hours",
    hint: "In this computer's time. A notice waits until they end; off for none.",
    placeholder: "22:00-08:00",
  },
  {
    key: "notice_kinds",
    label: "Say what kinds",
    hint: "on to say how many drafts, care items, steps and tasks; empty or off for a count alone, which says nothing on a lock screen.",
    placeholder: "off",
  },
];

/** A topic no one could guess: "proxenos-" and 24 random letters and digits, made in this browser. */
function newTopic(): string {
  const letters = "abcdefghijklmnopqrstuvwxyz0123456789";
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  // 252 is the largest multiple of 36 under 256: a byte past it would favour the first letters.
  let picked = "";
  for (const b of bytes) if (b < 252) picked += letters[b % 36];
  while (picked.length < 24) {
    const [b] = crypto.getRandomValues(new Uint8Array(1));
    if (b < 252) picked += letters[b % 36];
  }
  return `proxenos-${picked}`;
}

const FOLDERS: { key: SettingKey; label: string; hint: string; placeholder: string }[] = [
  {
    key: "docs_dirs",
    label: "Folders of documents",
    hint: "Read on every sync: a folder of health records, say. Separate several with commas.",
    placeholder: "~/Health, ~/Scans",
  },
  { key: "website_repo", label: "Your website", hint: "Its local git folder: pages, posts and CV data.", placeholder: "~/code/my-site" },
  {
    key: "spotify_export",
    label: "Spotify export",
    hint: "The folder of your Extended Streaming History download.",
    placeholder: "~/Downloads/Spotify Extended Streaming History",
  },
  { key: "slackdump_dir", label: "slackdump runs", hint: "A folder holding slackdump_* runs.", placeholder: "~/slackdump" },
  {
    key: "cv_dirs",
    label: "Where your CV is",
    hint: "More folders an errand looks in for your CV, comma-separated.",
    placeholder: "~/Career",
  },
];

/** The model light jobs go to, which a small one on this Mac does about twice as fast as the main one. */
const FAST_SETTINGS: { key: SettingKey; label: string; hint: string; placeholder: string }[] = [
  {
    key: "fast_model",
    label: "Fast model",
    hint: "local:<name> for a model another server on this computer has, ollama:<name> for one in Ollama; off to keep light jobs on the main model.",
    placeholder: "local:mlx-community/gemma-4-e4b-it-4bit",
  },
];

/** Where each project's folder goes: written each night, never read but for the manuscript's changes. */
const PROJECT_FOLDER: { key: SettingKey; label: string; hint: string; placeholder: string }[] = [
  {
    key: "project_folder",
    label: "Your projects' folder",
    hint: "A folder your cloud drive syncs: Google Drive for desktop, Dropbox, OneDrive or iCloud Drive. Empty: none.",
    placeholder: "~/Library/CloudStorage/GoogleDrive-…/My Drive/Projects",
  },
];

/** The model a paper's peer review runs on, which only Review it on the Projects page starts. */
const REVIEW_SETTINGS: { key: SettingKey; label: string; hint: string; placeholder: string }[] = [
  {
    key: "review_model",
    label: "Who reviews a paper",
    hint: "Empty: Claude with your key, else Claude Code. claude-code for Claude Code; ollama:<name> for a model on this computer.",
    placeholder: "claude-opus-5-5",
  },
];

function Group({ kicker, title, note, children }: { kicker: string; title: string; note?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <div>
        <p className="smallcaps">{kicker}</p>
        <h2 className="title-2">{title}</h2>
        {note && <p className="mt-1 text-sm leading-relaxed text-muted">{note}</p>}
      </div>
      {children}
    </section>
  );
}

/** A setting the shell sets wins over anything saved here; say so where it's edited. */
function FromShell({ values }: { values: SettingValue[] }) {
  if (!values.some((v) => v.from === "environment")) return null;
  return (
    <p className="text-xs leading-relaxed text-warn-ink">
      Set in the environment Proxenos was started with, which wins over what&apos;s saved here.
    </p>
  );
}

/** How this device shows the page and reads it aloud: kept in this browser, so it's there before anything else loads. */
function ReadingGroup() {
  return (
    <>
      <Group
        kicker="Reading"
        title="Easier to read"
        note="Kept on this device, in this browser. Aa at the top of every view changes these too."
      >
        <div className="card p-4 sm:p-5">
          <ReadingControls />
        </div>
      </Group>
      <Group
        kicker="Listening"
        title="Read aloud"
        note="Listen on Home, Care and Drafts reads with a natural voice or your own, made on this Mac, or with this device's voice. Nothing is sent anywhere to do it."
      >
        <div className="card p-4 sm:p-5">
          <VoiceControls />
        </div>
      </Group>
    </>
  );
}

/** Your settings, the model, the keys and sign-ins (whether each is set, never what it is), the folders read on every sync, and the one your projects go to. */
export function Settings() {
  const { status, error, reload, apply } = useSetup();
  if (!status) {
    return (
      <div className="space-y-8 p-4 pb-24 sm:p-6 md:pb-20">
        <ReadingGroup />
        {error ? <ErrorBanner message={`Couldn't read the settings: ${error}`} /> : <StatusSkeleton />}
      </div>
    );
  }

  return (
    <div className="space-y-8 p-4 pb-24 sm:p-6 md:pb-20">
      {error && <ErrorBanner message={error} />}
      <ReadingGroup />
      <section className="card flex items-start gap-3 p-5 sm:p-6">
        <div className="rounded-full bg-accent/10 p-2.5 text-accent">
          <SlidersHorizontal size={17} />
        </div>
        <div className="min-w-0 space-y-1">
          <p className="smallcaps">Where it&apos;s saved</p>
          <p className="leading-relaxed text-muted">
            {status.savesTo === ".env" ? (
              "Proxenos is running from source with an .env, so changes here are written there."
            ) : (
              <>
                Settings in <code className="num break-all text-ink">{status.settingsFile}</code>, and keys and tokens in the{" "}
                {status.secretStore}, one item each. This page never shows one back.
              </>
            )}{" "}
            <Link href="/setup" className="text-accent hover:underline">
              Run the setup again
            </Link>
          </p>
        </div>
      </section>

      <Group kicker="You" title="Your name">
        <NameForm status={status} apply={apply} />
      </Group>

      <Group kicker="Vault" title="Where your records live">
        <VaultForm status={status} apply={apply} />
      </Group>

      <Group kicker="Model" title="What drafts for you">
        <div className="card p-4 sm:p-5">
          <ModelChoice status={status} apply={apply} onReload={reload} />
        </div>
      </Group>

      <Group kicker="Model" title="Which writes like you?">
        <Compare status={status} />
      </Group>

      <Group
        kicker="Model"
        title="A faster one for light jobs"
        note="The task list, the network, the notes on each month, the research picks and the like read a lot and write to no one, so a small model on this Mac can do them in half the time. Drafts, Ask, Think, errands and calls stay on the model above. Every call is in the Privacy view."
      >
        <FastModel status={status} apply={apply} />
      </Group>

      <Group
        kicker="Secrets"
        title="Keys and sign-ins"
        note="Whether each is set and where it's kept, never what it is. Gmail and Slack accounts are added from Connect."
      >
        <div className="card divide-y divide-line">
          {status.secrets
            .filter((s) => !NOTICE_SECRETS.includes(s.name) && !LOOKUP_SECRETS.includes(s.name))
            .map((s) => (
              <SecretRow key={s.name} s={s} store={status.secretStore} apply={apply} />
            ))}
        </div>
      </Group>

      <Group
        kicker="Phone"
        title="Notices on your phone"
        note="When something new waits on you, one short notice through ntfy, an open-source push service: how many things wait, and how many of each kind only if you turn that on; never a name, a message's words or a health detail."
      >
        <NoticesCard status={status} apply={apply} />
      </Group>

      <Group
        kicker="Web"
        title="Looking people up"
        note="When an errand, Ask or Think needs someone's email address and your records have none, only that person's name and where they are go to a search engine, and only that organization's own pages are read. Nothing about you, and an address is never guessed."
      >
        <div className="card divide-y divide-line">
          {status.secrets
            .filter((s) => LOOKUP_SECRETS.includes(s.name))
            .map((s) => (
              <SecretRow key={s.name} s={s} store={status.secretStore} apply={apply} />
            ))}
        </div>
        <FoldersForm status={status} apply={apply} fields={LOOKUP_SETTINGS} button="Save" />
      </Group>

      <Group kicker="Folders" title="Read on every sync">
        <FoldersForm status={status} apply={apply} fields={FOLDERS} button="Save folders" />
      </Group>

      <Group
        kicker="Projects"
        title="In your cloud drive"
        note="Each night, each project's manuscript and Proxenos's notes on it go here as Word files, to read, edit, comment on and share in Word or Google Docs. Your drive uploads them; Proxenos shares nothing and reads nothing else there. What you change in a Markdown manuscript comes back as a step for you to accept; LaTeX goes one way. Needs pandoc (brew install pandoc)."
      >
        <FoldersForm status={status} apply={apply} fields={PROJECT_FOLDER} button="Save folder" />
      </Group>

      <Group
        kicker="Projects"
        title="Peer review"
        note="Review it on a project sends its manuscript, its code and its brief to this model, and nothing else of yours. It's heavy reasoning, so a hosted model is the default; every call is in the Privacy view."
      >
        <FoldersForm status={status} apply={apply} fields={REVIEW_SETTINGS} button="Save" />
      </Group>
    </div>
  );
}

/** Which model light jobs use and whether it's up, with one button to take the one this Mac can serve. */
function FastModel({ status, apply }: { status: SetupStatus; apply: Apply }) {
  const { fast } = status;
  const { busy, said, run } = useChange(apply);
  const on = fast.model !== null && fast.model !== "off";
  return (
    <div className="space-y-3">
      <div className="card space-y-3 p-4 text-sm leading-relaxed text-muted sm:p-5">
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {on ? (
            <>
              <StatePill on={fast.running} tone={fast.running ? undefined : "bad"} label={fast.running ? "Running" : "Not answering"} />
              <span className="min-w-0 break-words">
                Light jobs use <span className="num text-ink">{fast.model}</span>
                {fast.running ? "." : ", and go to the main model until its server is up: proxenos model serve-fast."}
              </span>
            </>
          ) : fast.model === "off" ? (
            "Off: light jobs use the main model."
          ) : fast.found ? (
            "This Mac has mlx-lm and the model, and none is set yet."
          ) : (
            "None set: light jobs use the main model. On a Mac with Apple silicon and mlx-lm, proxenos model serve-fast serves one."
          )}
        </p>
        {!on && fast.found && fast.suggested && (
          <PrimaryButton disabled={busy} onClick={() => run({ settings: { fast_model: fast.suggested } })}>
            Use {fast.suggested.replace(/^local:/, "")}
          </PrimaryButton>
        )}
        <SaidLine said={said} />
      </div>
      <FoldersForm key={fast.model ?? ""} status={status} apply={apply} fields={FAST_SETTINGS} button="Save" />
    </div>
  );
}

function NameForm({ status, apply }: { status: SetupStatus; apply: Apply }) {
  const saved = status.settings.name.value ?? "";
  const [name, setName] = useState(saved);
  const { busy, said, run } = useChange(apply);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        run({ settings: { name } });
      }}
      className="card space-y-3 p-4 sm:p-5"
    >
      <div className="grid gap-2.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
        <Field label="What Proxenos calls you">
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} className={inputClass} {...NOT_A_LOGIN} />
        </Field>
        <PrimaryButton type="submit" disabled={busy || name.trim() === saved}>
          <Save size={14} aria-hidden="true" />
          Save
        </PrimaryButton>
      </div>
      <p className="text-xs leading-relaxed text-muted">In its notes and the picture of you it writes.</p>
      <FromShell values={[status.settings.name]} />
      <SaidLine said={said} />
    </form>
  );
}

function VaultForm({ status, apply }: { status: SetupStatus; apply: Apply }) {
  const saved = status.settings.vault.value ?? status.vault.path;
  const [vault, setVault] = useState(saved);
  const { busy, said, run } = useChange(apply);
  const typed = vault.trim();
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        run({ settings: { vault: typed } });
      }}
      className="card space-y-3 p-4 sm:p-5"
    >
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
        <StatePill
          on={status.vault.exists}
          tone={status.vault.exists ? undefined : "bad"}
          label={status.vault.exists ? "Found" : "Not there"}
        />
        <span className="num min-w-0 break-all text-ink">{status.vault.path}</span>
        {!status.settings.vault.value && <span className="text-xs text-faint">the default</span>}
      </p>
      <div className="grid gap-2.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
        <Field label="Folder">
          <input value={vault} onChange={(e) => setVault(e.target.value)} className={cn(inputClass, "num")} {...NOT_A_LOGIN} />
        </Field>
        <PrimaryButton type="submit" disabled={busy || !typed || typed === saved}>
          <Save size={14} aria-hidden="true" />
          Save
        </PrimaryButton>
      </div>
      <p className="text-xs leading-relaxed text-muted">
        Changing it moves nothing: Proxenos starts reading and writing the new folder, and the old one stays as it is.
      </p>
      <CloudWarning where={typed === saved ? status.vault.cloud : cloudFor(typed, status.home)} />
      <FromShell values={[status.settings.vault]} />
      <SaidLine said={said} />
    </form>
  );
}

function SecretRow({ s, store, apply }: { s: SecretState; store: string; apply: Apply }) {
  const [mode, setMode] = useState<"idle" | "replace" | "remove">("idle");
  const [value, setValue] = useState("");
  const { busy, said, run } = useChange(apply);
  const fromShell = s.from === "environment";
  const done = (ok: boolean) => {
    if (!ok) return;
    setMode("idle");
    setValue("");
  };
  const hint = s.name.startsWith("GMAIL_")
    ? "address:app password. Or sign in again from Connect."
    : s.name === "ANTHROPIC_API_KEY" || s.name === "OPENAI_API_KEY" || s.name === "GEMINI_API_KEY"
      ? "Checked with its provider before it's saved."
      : s.name === "NTFY_TOPIC"
        ? "20 to 64 letters, digits, - and _, random. The same name you subscribed to in the app."
        : s.name === "NTFY_TOKEN"
          ? "Only for a server that asks for one. ntfy.sh doesn't."
          : s.name === "BRAVE_SEARCH_KEY"
            ? "From api-dashboard.search.brave.com. It goes only to Brave, with each search."
            : null;

  return (
    <div className="space-y-3 px-4 py-3.5">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="min-w-0">
          <div className="break-words font-medium text-ink">{secretLabel(s.name)}</div>
          <div className="num break-all text-xs text-faint">{s.name}</div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <StatePill on={s.set} label={s.set ? `Set ${originLabel(s.from, store)}` : "Not set"} />
          {mode === "idle" && (
            <>
              <button
                type="button"
                onClick={() => setMode("replace")}
                className="inline-flex items-center gap-1.5 rounded-full border border-line-strong px-3 py-1 text-[0.8125rem] text-muted transition-colors hover:text-ink"
              >
                <KeyRound size={13} aria-hidden="true" />
                {s.set ? "Replace" : "Add"}
              </button>
              {s.set && !fromShell && (
                <button
                  type="button"
                  onClick={() => setMode("remove")}
                  aria-label={`Remove ${secretLabel(s.name)}`}
                  className="rounded-full p-1.5 text-muted transition-colors hover:text-bad-ink"
                >
                  <Trash2 size={14} aria-hidden="true" />
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {mode === "replace" && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run({ secret: s.name, value }).then(done);
          }}
          className="space-y-2"
        >
          <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center">
            <input
              type="password"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder={s.set ? "The new value" : "Paste it here"}
              aria-label={`New ${secretLabel(s.name)}`}
              // eslint-disable-next-line jsx-a11y/no-autofocus -- shown by the reader's own Replace, so focus follows it
              autoFocus
              className={inputClass}
              {...NOT_A_LOGIN}
            />
            <PrimaryButton type="submit" disabled={busy || !value.trim()}>
              {busy ? "Saving…" : "Save"}
            </PrimaryButton>
            <button type="button" onClick={() => setMode("idle")} className="rounded-full px-2 py-1.5 text-sm text-muted hover:text-ink">
              Cancel
            </button>
          </div>
          {hint && <p className="text-xs text-muted">{hint}</p>}
        </form>
      )}

      {mode === "remove" && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-bad-line bg-bad-bg px-3.5 py-2.5 text-sm text-bad-ink">
          <span className="min-w-0 flex-1">
            Remove it from {originLabel(s.from, store).replace(/^in /, "") || "where it's kept"}? Whatever reads it stops working.
          </span>
          <button
            type="button"
            disabled={busy}
            onClick={() => run({ forget: s.name }).then(done)}
            className="rounded-full bg-bad-ink px-3 py-1 text-[0.8125rem] font-medium text-bg disabled:opacity-50"
          >
            Remove
          </button>
          <button type="button" onClick={() => setMode("idle")} className="text-[0.8125rem] text-bad-ink/80 hover:text-bad-ink">
            Keep
          </button>
        </div>
      )}
      {fromShell && mode === "idle" && (
        <p className="text-xs text-muted">Set in the environment Proxenos was started with; change it there.</p>
      )}
      <SaidLine said={said} />
    </div>
  );
}

/** Phone notices: how to set them up, the topic and token, the server and quiet hours, and a test. */
function NoticesCard({ status, apply }: { status: SetupStatus; apply: Apply }) {
  const rows = status.secrets.filter((s) => NOTICE_SECRETS.includes(s.name));
  const topicSet = rows.some((s) => s.name === "NTFY_TOPIC" && s.set);
  return (
    <div className="card divide-y divide-line">
      <ol className="list-decimal space-y-1 py-3.5 pl-9 pr-4 text-sm leading-relaxed text-muted">
        <li>Install the ntfy app, on Android or iOS.</li>
        <li>
          Make a long, random topic name below, and subscribe to it in the app. On ntfy.sh anyone who knows a topic can read
          what&apos;s sent to it, so keep it like a password.
        </li>
        <li>Save it here as the topic.</li>
      </ol>
      <MakeTopic />
      {rows.map((s) => (
        <SecretRow key={s.name} s={s} store={status.secretStore} apply={apply} />
      ))}
      <NoticeSettings status={status} apply={apply} />
      <TestNotice ready={topicSet} />
    </div>
  );
}

/**
 * Make a topic in this browser, to copy into the ntfy app and then save below. It's made here, not
 * by the server, so it never comes back from it, as no saved secret does.
 */
function MakeTopic() {
  const [topic, setTopic] = useState<string | null>(null);
  return (
    <div className="flex flex-wrap items-center gap-2 px-4 py-3.5">
      <button
        type="button"
        onClick={() => setTopic(newTopic())}
        className="rounded-full border border-line-strong px-3 py-1.5 text-[0.8125rem] text-muted transition-colors hover:text-ink"
      >
        Make one
      </button>
      {topic && (
        <code className="num select-all break-all rounded bg-surface-2 px-2 py-1 text-sm text-ink" aria-label="A new topic">
          {topic}
        </code>
      )}
    </div>
  );
}

function NoticeSettings({ status, apply }: { status: SetupStatus; apply: Apply }) {
  const savedOf = (key: SettingKey) => status.settings[key].value ?? "";
  const [values, setValues] = useState<Partial<Record<SettingKey, string>>>(() =>
    Object.fromEntries(NOTICE_SETTINGS.map((f) => [f.key, savedOf(f.key)])),
  );
  const { busy, said, run } = useChange(apply);
  const changed = Object.fromEntries(
    NOTICE_SETTINGS.flatMap((f) => (values[f.key]?.trim() !== savedOf(f.key) ? [[f.key, values[f.key]?.trim() ?? ""]] : [])),
  );
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        run({ settings: changed });
      }}
      className="space-y-4 px-4 py-3.5"
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {NOTICE_SETTINGS.map((f) => (
          <Field key={f.key} label={f.label} hint={f.hint}>
            <input
              value={values[f.key] ?? ""}
              onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
              placeholder={f.placeholder}
              className={cn(inputClass, "num")}
              {...NOT_A_LOGIN}
            />
          </Field>
        ))}
      </div>
      <FromShell values={NOTICE_SETTINGS.map((f) => status.settings[f.key])} />
      <div className="flex items-center justify-between gap-3">
        <SaidLine said={said} />
        <span className="ml-auto">
          <PrimaryButton type="submit" disabled={busy || !Object.keys(changed).length}>
            <Save size={14} aria-hidden="true" />
            Save
          </PrimaryButton>
        </span>
      </div>
    </form>
  );
}

/** One test notice, through the command, which keeps the topic to itself. */
function TestNotice({ ready }: { ready: boolean }) {
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<Said>(null);
  const test = async () => {
    setBusy(true);
    setSaid(null);
    try {
      const res = await fetch("/api/notify", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ test: true }),
      });
      const answer = (await res.json().catch(() => ({}))) as Partial<NoticeTest> & { error?: string };
      setSaid({ ok: res.ok && answer.ok === true, text: answer.message ?? answer.error ?? `The test didn't go through (${res.status}).` });
    } catch (e) {
      setSaid({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-2 px-4 py-3.5">
      <div className="flex flex-wrap items-center gap-3">
        <PrimaryButton onClick={test} disabled={busy || !ready}>
          <BellRing size={14} aria-hidden="true" />
          {busy ? "Sending…" : "Send a test"}
        </PrimaryButton>
        <span className="text-xs text-muted">
          {ready ? "Your phone should show it in a few seconds." : "Save a topic first."}
        </span>
      </div>
      <SaidLine said={said} />
    </div>
  );
}

function FoldersForm({
  status,
  apply,
  fields,
  button,
}: {
  status: SetupStatus;
  apply: Apply;
  fields: typeof FOLDERS;
  button: string;
}) {
  const savedOf = (key: SettingKey) => status.settings[key].value ?? "";
  const [values, setValues] = useState<Partial<Record<SettingKey, string>>>(() =>
    Object.fromEntries(fields.map((f) => [f.key, savedOf(f.key)])),
  );
  const { busy, said, run } = useChange(apply);
  const changed = Object.fromEntries(
    fields.flatMap((f) => (values[f.key]?.trim() !== savedOf(f.key) ? [[f.key, values[f.key]?.trim() ?? ""]] : [])),
  );

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        run({ settings: changed });
      }}
      className="card space-y-4 p-4 sm:p-5"
    >
      {fields.map((f) => (
        <Field key={f.key} label={f.label} hint={f.hint}>
          <input
            value={values[f.key] ?? ""}
            onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
            placeholder={f.placeholder}
            className={cn(inputClass, "num")}
            {...NOT_A_LOGIN}
          />
        </Field>
      ))}
      <FromShell values={fields.map((f) => status.settings[f.key])} />
      <div className="flex items-center justify-between gap-3">
        <SaidLine said={said} />
        <span className="ml-auto">
          <PrimaryButton type="submit" disabled={busy || !Object.keys(changed).length}>
            <Save size={14} aria-hidden="true" />
            {button}
          </PrimaryButton>
        </span>
      </div>
    </form>
  );
}
