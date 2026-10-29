"use client";

import { KeyRound, Save, SlidersHorizontal, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PrimaryButton, StatePill } from "@/components/connect/parts";
import { ErrorBanner } from "@/components/EmptyState";
import {
  type Apply,
  CloudWarning,
  Field,
  inputClass,
  ModelChoice,
  NOT_A_LOGIN,
  originLabel,
  SaidLine,
  secretLabel,
  useChange,
} from "@/components/setup/parts";
import { StatusSkeleton } from "@/components/Skeleton";
import { cloudFor, useSetup } from "@/lib/setupClient";
import type { SecretState, SettingKey, SettingValue, SetupStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

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

/** Your settings, the model, the keys and sign-ins (whether each is set, never what it is), and the folders read on every sync. */
export function Settings() {
  const { status, error, reload, apply } = useSetup();
  if (!status) return error ? <ErrorBanner message={`Couldn't read the settings: ${error}`} /> : <StatusSkeleton />;

  return (
    <div className="space-y-8 p-4 pb-24 sm:p-6 md:pb-20">
      {error && <ErrorBanner message={error} />}
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

      <Group
        kicker="Secrets"
        title="Keys and sign-ins"
        note="Whether each is set and where it's kept, never what it is. Gmail and Slack accounts are added from Connect."
      >
        <div className="card divide-y divide-line">
          {status.secrets.map((s) => (
            <SecretRow key={s.name} s={s} store={status.secretStore} apply={apply} />
          ))}
        </div>
      </Group>

      <Group kicker="Folders" title="Read on every sync">
        <FoldersForm status={status} apply={apply} />
      </Group>
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
    : s.name === "ANTHROPIC_API_KEY"
      ? "Checked with Anthropic before it's saved."
      : null;

  return (
    <div className="space-y-3 px-4 py-3.5">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="min-w-0">
          <div className="font-medium text-ink">{secretLabel(s.name)}</div>
          <div className="num text-xs text-faint">{s.name}</div>
        </div>
        <div className="flex items-center gap-3">
          <StatePill on={s.set} label={s.set ? `Set ${originLabel(s.from, store)}` : "Not set"} />
          {mode === "idle" && (
            <>
              <button
                type="button"
                onClick={() => setMode("replace")}
                className="inline-flex items-center gap-1.5 rounded-full border border-line-strong px-3 py-1 text-[13px] text-muted transition-colors hover:text-ink"
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
            className="rounded-full bg-bad-ink px-3 py-1 text-[13px] font-medium text-bg disabled:opacity-50"
          >
            Remove
          </button>
          <button type="button" onClick={() => setMode("idle")} className="text-[13px] text-bad-ink/80 hover:text-bad-ink">
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

function FoldersForm({ status, apply }: { status: SetupStatus; apply: Apply }) {
  const savedOf = (key: SettingKey) => status.settings[key].value ?? "";
  const [values, setValues] = useState<Partial<Record<SettingKey, string>>>(() =>
    Object.fromEntries(FOLDERS.map((f) => [f.key, savedOf(f.key)])),
  );
  const { busy, said, run } = useChange(apply);
  const changed = Object.fromEntries(
    FOLDERS.flatMap((f) => (values[f.key]?.trim() !== savedOf(f.key) ? [[f.key, values[f.key]?.trim() ?? ""]] : [])),
  );

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        run({ settings: changed });
      }}
      className="card space-y-4 p-4 sm:p-5"
    >
      {FOLDERS.map((f) => (
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
      <FromShell values={FOLDERS.map((f) => status.settings[f.key])} />
      <div className="flex items-center justify-between gap-3">
        <SaidLine said={said} />
        <span className="ml-auto">
          <PrimaryButton type="submit" disabled={busy || !Object.keys(changed).length}>
            <Save size={14} aria-hidden="true" />
            Save folders
          </PrimaryButton>
        </span>
      </div>
    </form>
  );
}
