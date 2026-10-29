"use client";

import { Check, Cpu, KeyRound, RefreshCw, TriangleAlert, X } from "lucide-react";
import { useState } from "react";

import { PrimaryButton } from "@/components/connect/parts";
import { Command } from "@/components/EmptyState";
import { Segmented } from "@/components/layout/Segmented";
import type { SetupChange, SettingOrigin, SetupStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

export const inputClass =
  "w-full rounded-lg border border-line-strong bg-bg px-3 py-2 text-sm text-ink placeholder:text-muted/80 focus:border-accent/60 focus:outline-none disabled:opacity-60";

/** Fields a password manager should leave alone: these hold a path, a name or a key it didn't make. */
export const NOT_A_LOGIN = {
  autoComplete: "off",
  autoCapitalize: "off",
  spellCheck: false,
  "data-1p-ignore": true,
  "data-lpignore": "true",
};

export const DEFAULT_LOCAL_MODEL = "gemma4:26b";

export type Apply = (change: SetupChange) => Promise<string>;
export type Said = { ok: boolean; text: string } | null;

/** One change at a time from a form: busy while it's saved, then what was said. Resolves with whether it worked. */
export function useChange(apply: Apply) {
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<Said>(null);
  const run = (change: SetupChange): Promise<boolean> => {
    setBusy(true);
    setSaid(null);
    return apply(change)
      .then(
        (text) => {
          setSaid({ ok: true, text });
          return true;
        },
        (e: unknown) => {
          setSaid({ ok: false, text: e instanceof Error ? e.message : String(e) });
          return false;
        },
      )
      .finally(() => setBusy(false));
  };
  return { busy, said, run, clear: () => setSaid(null) };
}

/** What a change did: a quiet green line when it worked, a red one when it didn't. */
export function SaidLine({ said }: { said: Said }) {
  if (!said) return null;
  const Icon = said.ok ? Check : X;
  return (
    <p
      className={cn("flex items-start gap-1.5 text-sm leading-relaxed", said.ok ? "text-ok-ink" : "text-bad-ink")}
      role={said.ok ? "status" : "alert"}
    >
      <Icon size={15} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
      <span className="min-w-0 break-words">{said.text}</span>
    </p>
  );
}

/** A labelled box with a line under it saying what it's for. */
export function Field({ label, hint, children }: { label: string; hint?: React.ReactNode; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm text-ink">{label}</span>
      {children}
      {hint && <span className="block text-xs leading-relaxed text-muted">{hint}</span>}
    </label>
  );
}

/** A vault in a folder a cloud copies: it would leave the Mac, so say so before it's saved. */
export function CloudWarning({ where }: { where: "icloud" | "drive" | null }) {
  if (!where) return null;
  return (
    <div
      className="flex items-start gap-2.5 rounded-xl border border-warn-line bg-warn-bg px-3.5 py-2.5 text-sm text-warn-ink"
      role="status"
    >
      <TriangleAlert size={16} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
      <span className="leading-relaxed">
        {where === "icloud"
          ? "iCloud may copy this folder to Apple's servers: Desktop and Documents sync whenever Desktop & Documents Folders is on in iCloud Drive."
          : "This is a cloud drive's folder, which copies it to that service's servers."}{" "}
        Your records would leave this Mac. A folder straight in your home folder, like ~/proxenos_vault, stays here.
      </span>
    </div>
  );
}

/** Where a value is kept, in the page's words. `store` names the secure store, as SetupStatus.secretStore does. */
export function originLabel(from: SettingOrigin | null, store: string): string {
  if (from === "keychain") return `in the ${store}`;
  if (from === ".env") return "in .env";
  if (from === "settings") return "in your settings";
  if (from === "environment") return "from the environment";
  return "";
}

/** Which model drafts: one on this Mac through Ollama, or Anthropic's with your key. */
export function ModelChoice({ status, apply, onReload }: { status: SetupStatus; apply: Apply; onReload: () => void }) {
  const [tab, setTab] = useState<"local" | "api">(status.model.kind === "api" ? "api" : "local");
  const { model } = status;
  return (
    <div className="space-y-4">
      <p className="flex items-center gap-2 text-sm text-muted">
        <span className={cn("h-2 w-2 rounded-full", model.kind === "none" ? "bg-muted/60" : "bg-ok-ink")} aria-hidden="true" />
        {model.kind === "local" ? (
          <span>
            Using <span className="num text-ink">{model.name}</span> on this Mac.
          </span>
        ) : model.kind === "api" ? (
          <span>
            Using <span className="num text-ink">{model.name}</span> through Anthropic, with your key.
          </span>
        ) : (
          "No model yet."
        )}
      </p>
      <Segmented
        label="Where the model runs"
        tabs={[
          { id: "local", label: "On this Mac" },
          { id: "api", label: "Anthropic API key" },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "local" ? <LocalModel status={status} apply={apply} onReload={onReload} /> : <ApiKey status={status} apply={apply} />}
    </div>
  );
}

function LocalModel({ status, apply, onReload }: { status: SetupStatus; apply: Apply; onReload: () => void }) {
  const { running, models } = status.ollama;
  const current = status.model.kind === "local" ? status.model.name : null;
  const [pick, setPick] = useState(current ?? (models.includes(DEFAULT_LOCAL_MODEL) ? DEFAULT_LOCAL_MODEL : (models[0] ?? "")));
  const { busy, said, run } = useChange(apply);
  const chosen = models.includes(pick) ? pick : (models[0] ?? "");

  return (
    <div className="space-y-3">
      <p className="text-sm leading-relaxed text-muted">
        An open model running on this Mac through Ollama: nothing leaves the computer, and there&apos;s no account or key.{" "}
        <span className="num">{DEFAULT_LOCAL_MODEL}</span> is about 17 GB and fits a Mac with 32 GB of memory.
      </p>
      {!running || !models.length ? (
        <div className="space-y-3 rounded-xl border border-line-strong bg-surface-2/60 p-3.5">
          <ol className="list-decimal space-y-1.5 pl-5 text-sm leading-relaxed text-muted marker:text-faint">
            {!running && (
              <li>
                Install Ollama from{" "}
                <a href="https://ollama.com/download" target="_blank" rel="noreferrer" className="text-accent hover:underline">
                  ollama.com
                </a>{" "}
                and open it.
              </li>
            )}
            <li>
              Pull a model in Terminal: <Command>{`ollama pull ${DEFAULT_LOCAL_MODEL}`}</Command>
            </li>
          </ol>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={onReload}
              className="inline-flex items-center gap-1.5 rounded-full border border-line-strong px-3.5 py-1.5 text-sm text-muted transition-colors hover:text-ink"
            >
              <RefreshCw size={14} aria-hidden="true" />
              Check again
            </button>
            <span className="text-xs text-faint">{running ? "Ollama is running, with no model yet." : "Ollama isn't running."}</span>
          </div>
        </div>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run({ ollama: chosen });
          }}
          className="grid gap-2.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end"
        >
          <Field label="Model">
            <select value={chosen} onChange={(e) => setPick(e.target.value)} className={inputClass}>
              {models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </Field>
          <PrimaryButton type="submit" disabled={busy || chosen === current}>
            <Cpu size={14} aria-hidden="true" />
            {busy ? "Checking…" : chosen === current ? "In use" : "Use this model"}
          </PrimaryButton>
        </form>
      )}
      <SaidLine said={said} />
    </div>
  );
}

function ApiKey({ status, apply }: { status: SetupStatus; apply: Apply }) {
  const [key, setKey] = useState("");
  const { busy, said, run } = useChange(apply);
  const saved = status.secrets.find((s) => s.name === "ANTHROPIC_API_KEY");
  const where = status.savesTo === ".env" ? "the repo's .env" : status.keychain ? `the ${status.secretStore}` : "your settings";

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    run({ key }).then((ok) => ok && setKey(""));
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <p className="text-sm leading-relaxed text-muted">
        Anthropic&apos;s models, with a personal key from{" "}
        <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer" className="text-accent hover:underline">
          console.anthropic.com
        </a>
        , kept apart from any work account. A step that drafts sends what it needs to Anthropic under your key.
      </p>
      <div className="grid gap-2.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
        <Field label={saved?.set ? "Replace the key" : "API key"}>
          <input
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder={saved?.set ? `Saved ${originLabel(saved.from, status.secretStore)}` : "sk-ant-…"}
            className={inputClass}
            {...NOT_A_LOGIN}
          />
        </Field>
        <PrimaryButton type="submit" disabled={busy || !key.trim()}>
          <KeyRound size={14} aria-hidden="true" />
          {busy ? "Checking…" : "Check and save"}
        </PrimaryButton>
      </div>
      <p className="text-xs leading-relaxed text-muted">
        Proxenos asks Anthropic once whether the key works, then keeps it in {where}. This page never shows it again.
      </p>
      <SaidLine said={said} />
    </form>
  );
}

/** A secret's name in the page's words. */
export function secretLabel(name: string): string {
  const fixed: Record<string, string> = {
    ANTHROPIC_API_KEY: "Anthropic API key",
    BEEPER_ACCESS_TOKEN: "Beeper token",
    STRAVA_REFRESH_TOKEN: "Strava sign-in",
    STRAVA_CLIENT_ID: "Strava app ID",
    STRAVA_CLIENT_SECRET: "Strava app secret",
    GOOGLE_CLIENT_ID: "Google sign-in client ID",
    GOOGLE_CLIENT_SECRET: "Google sign-in client secret",
    MICROSOFT_CLIENT_ID: "Microsoft sign-in client ID",
    SLACK_USER_TOKEN: "Slack token",
  };
  if (fixed[name]) return fixed[name];
  if (name.startsWith("GMAIL_")) return `Gmail · ${name.slice(6).toLowerCase()}`;
  if (name.startsWith("GCALENDAR_")) return `Google Calendar · ${name.slice(10).toLowerCase()}`;
  if (name.startsWith("MICROSOFT_")) return `Microsoft · ${name.slice(10).toLowerCase()}`;
  if (name.startsWith("SLACK_USER_TOKEN_")) return `Slack · ${name.slice(17)}`;
  return name;
}
