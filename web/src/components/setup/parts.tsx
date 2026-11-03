"use client";

import { Check, Cpu, KeyRound, RefreshCw, TriangleAlert, X } from "lucide-react";
import { useState } from "react";

import { PrimaryButton } from "@/components/connect/parts";
import { Command } from "@/components/EmptyState";
import { Segmented } from "@/components/layout/Segmented";
import type { LocalModel, SetupChange, SettingOrigin, SetupStatus } from "@/lib/types";
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

/** Which model drafts: one on this computer, through Ollama or another app's server, or Anthropic's with your key. */
export function ModelChoice({ status, apply, onReload }: { status: SetupStatus; apply: Apply; onReload: () => void }) {
  const [tab, setTab] = useState<"local" | "api">(status.model.kind === "api" ? "api" : "local");
  const { model } = status;
  return (
    <div className="space-y-4">
      <p className="flex items-center gap-2 text-sm text-muted">
        <span className={cn("h-2 w-2 flex-shrink-0 rounded-full", model.kind === "none" ? "bg-muted/60" : "bg-ok-ink")} aria-hidden="true" />
        {model.kind === "local" ? (
          <span className="min-w-0 break-words">
            Using <span className="num text-ink">{model.name}</span> on this computer
            {model.via === "server" ? (
              <>
                , through the server at <span className="num">{status.server.url}</span>
              </>
            ) : (
              ", through Ollama"
            )}
            .
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
          { id: "local", label: "On this computer" },
          { id: "api", label: "Anthropic API key" },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "local" ? <OnThisComputer status={status} apply={apply} onReload={onReload} /> : <ApiKey status={status} apply={apply} />}
    </div>
  );
}

/** An open model on this computer: through Ollama, or another app that serves OpenAI's API, such as LM Studio. */
function OnThisComputer({ status, apply, onReload }: { status: SetupStatus; apply: Apply; onReload: () => void }) {
  const [via, setVia] = useState<"ollama" | "server">(
    status.model.via ?? (status.server.running && !status.ollama.running ? "server" : "ollama"),
  );
  return (
    <div className="space-y-3">
      <p className="text-sm leading-relaxed text-muted">
        An open model running on this computer: nothing leaves it, and there&apos;s no account or key. {status.computer.advice}
      </p>
      <Segmented
        label="What runs the model"
        tabs={[
          { id: "ollama", label: "Ollama" },
          { id: "server", label: "LM Studio and others" },
        ]}
        value={via}
        onChange={setVia}
      />
      {via === "ollama" ? (
        <OllamaModel status={status} apply={apply} onReload={onReload} />
      ) : (
        <ServerModel status={status} apply={apply} onReload={onReload} />
      )}
    </div>
  );
}

function OllamaModel({ status, apply, onReload }: { status: SetupStatus; apply: Apply; onReload: () => void }) {
  const { running, models, suggested } = status.ollama;
  const { busy, said, run } = useChange(apply);
  const get = status.computer.get;
  return (
    <div className="space-y-3">
      {!running || !models.length ? (
        <Missing onReload={onReload} state={running ? "Ollama is running, with no model yet." : "Ollama isn't running."}>
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
            {get ? (
              <>
                Pull a model in Terminal: <Command>{`ollama pull ${get}`}</Command>
              </>
            ) : (
              <>
                Pull a model of the size above from{" "}
                <a href="https://ollama.com/search" target="_blank" rel="noreferrer" className="text-accent hover:underline">
                  ollama.com/search
                </a>
                , in Terminal: <Command>ollama pull NAME</Command>
              </>
            )}
          </li>
        </Missing>
      ) : (
        <ModelPicker
          models={models}
          suggested={suggested}
          current={status.model.via === "ollama" ? status.model.name : null}
          rule={status.computer.rule}
          busy={busy}
          onUse={(name) => run({ ollama: name })}
        />
      )}
      <SaidLine said={said} />
    </div>
  );
}

/** A model another app serves on this computer through OpenAI's API: LM Studio, llama.cpp's llama-server, Jan, LocalAI or vLLM. */
function ServerModel({ status, apply, onReload }: { status: SetupStatus; apply: Apply; onReload: () => void }) {
  const { running, models, suggested, url, error, context } = status.server;
  const { busy, said, run } = useChange(apply);
  return (
    <div className="space-y-3">
      <p className="text-sm leading-relaxed text-muted">
        Any app that serves OpenAI&apos;s API on this computer: LM Studio, llama.cpp&apos;s llama-server, Jan, LocalAI or vLLM. Load the
        model there with a context of <span className="num">{context.toLocaleString("en-US")}</span> tokens, as long as
        Proxenos&apos;s longest prompts.
      </p>
      <ServerAddress status={status} apply={apply} />
      {error ? null : !running || !models.length ? (
        <Missing onReload={onReload} state={running ? `The server at ${url} has no model loaded.` : `Nothing answers at ${url}.`}>
          {!running && (
            <li>
              Start its server: in LM Studio, from the Developer tab. For llama-server, give its address above as
              http://127.0.0.1:8080/v1 and run <Command>{`llama-server -m MODEL.gguf -c ${context} --port 8080`}</Command>
            </li>
          )}
          <li>Load a model of the size above there.</li>
        </Missing>
      ) : (
        <ModelPicker
          models={models}
          suggested={suggested}
          current={status.model.via === "server" ? status.model.name : null}
          rule={status.computer.rule}
          busy={busy}
          onUse={(name) => run({ server: name })}
        />
      )}
      <SaidLine said={said} />
    </div>
  );
}

/** Where the server is: LM Studio's address unless another is saved, and only ever this computer's own. */
function ServerAddress({ status, apply }: { status: SetupStatus; apply: Apply }) {
  const saved = status.settings.local_url.value ?? "";
  const [address, setAddress] = useState(saved || status.server.url);
  const { busy, said, run } = useChange(apply);
  const { error } = status.server;
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        run({ settings: { local_url: address.trim() } });
      }}
      className="space-y-2"
    >
      <div className="grid gap-2.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
        <Field label="Server address">
          <input
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="http://127.0.0.1:1234/v1"
            className={cn(inputClass, "num")}
            {...NOT_A_LOGIN}
          />
        </Field>
        <button
          type="submit"
          disabled={busy || address.trim().replace(/\/+$/, "") === status.server.url}
          className="rounded-full border border-line-strong px-3.5 py-2 text-sm text-muted transition-colors hover:text-ink disabled:opacity-60"
        >
          {busy ? "Saving…" : "Save address"}
        </button>
      </div>
      {error && (
        <p className="flex items-start gap-1.5 text-sm leading-relaxed text-bad-ink" role="alert">
          <X size={15} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
          <span className="min-w-0 break-words">{error}</span>
        </p>
      )}
      <SaidLine said={said} />
    </form>
  );
}

/** What to do while a server has no model to pick: the steps, then a way to look again. */
function Missing({ state, onReload, children }: { state: string; onReload: () => void; children: React.ReactNode }) {
  return (
    <div className="space-y-3 rounded-xl border border-line-strong bg-surface-2/60 p-3.5">
      <ol className="list-decimal space-y-1.5 pl-5 text-sm leading-relaxed text-muted marker:text-faint">{children}</ol>
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onReload}
          className="inline-flex items-center gap-1.5 rounded-full border border-line-strong px-3.5 py-1.5 text-sm text-muted transition-colors hover:text-ink"
        >
          <RefreshCw size={14} aria-hidden="true" />
          Check again
        </button>
        <span className="min-w-0 break-words text-xs text-faint">{state}</span>
      </div>
    </div>
  );
}

/** A model's size as Ollama gives it: 17 GB, or 0.6 GB for a small one. */
function size(bytes: number): string {
  return bytes >= 1e9 ? `${Math.round(bytes / 1e9)} GB` : `${(bytes / 1e9).toFixed(1)} GB`;
}

/** A server's models to pick from, each with its size, the ones too big for this computer marked, and the largest that fits first. */
function ModelPicker({
  models,
  suggested,
  current,
  rule,
  busy,
  onUse,
}: {
  models: LocalModel[];
  suggested: string | null;
  current: string | null;
  rule: string;
  busy: boolean;
  onUse: (name: string) => void;
}) {
  const names = models.map((m) => m.name);
  const [pick, setPick] = useState(current ?? suggested ?? (names.includes(DEFAULT_LOCAL_MODEL) ? DEFAULT_LOCAL_MODEL : (names[0] ?? "")));
  const chosen = names.includes(pick) ? pick : (names[0] ?? "");
  const picked = models.find((m) => m.name === chosen);
  const label = (m: LocalModel) =>
    [m.name, m.bytes ? size(m.bytes) : null, m.fits === false ? "too big for this computer" : m.name === suggested ? "suggested" : null]
      .filter(Boolean)
      .join(" · ");
  return (
    <div className="space-y-2">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onUse(chosen);
        }}
        className="grid gap-2.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end"
      >
        <Field label="Model">
          <select value={chosen} onChange={(e) => setPick(e.target.value)} className={inputClass}>
            {models.map((m) => (
              <option key={m.name} value={m.name}>
                {label(m)}
              </option>
            ))}
          </select>
        </Field>
        <PrimaryButton type="submit" disabled={busy || chosen === current}>
          <Cpu size={14} aria-hidden="true" />
          {busy ? "Checking…" : chosen === current ? "In use" : "Use this model"}
        </PrimaryButton>
      </form>
      {picked?.fits === false && (
        <p className="flex items-start gap-1.5 text-sm leading-relaxed text-warn-ink" role="status">
          <TriangleAlert size={15} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
          <span>
            This one is too big for this computer&apos;s memory: it would be slow, or fail.
            {suggested && (
              <>
                {" "}
                <span className="num">{suggested}</span> fits.
              </>
            )}
          </span>
        </p>
      )}
      {models.some((m) => m.fits !== null) && <p className="text-xs leading-relaxed text-muted">{rule}</p>}
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
    SPOTIFY_CLIENT_ID: "Spotify app ID",
    SPOTIFY_REFRESH_TOKEN: "Spotify sign-in",
    GOOGLE_CLIENT_ID: "Google sign-in client ID",
    GOOGLE_CLIENT_SECRET: "Google sign-in client secret",
    MICROSOFT_CLIENT_ID: "Microsoft sign-in client ID",
    TWILIO_ACCOUNT_SID: "Twilio account SID (calls)",
    TWILIO_AUTH_TOKEN: "Twilio auth token (calls)",
    NTFY_TOPIC: "ntfy topic (phone notices)",
    NTFY_TOKEN: "ntfy token (phone notices)",
    SLACK_USER_TOKEN: "Slack token",
  };
  if (fixed[name]) return fixed[name];
  if (name.startsWith("GMAIL_")) return `Gmail · ${name.slice(6).toLowerCase()}`;
  if (name.startsWith("GCALENDAR_")) return `Google Calendar · ${name.slice(10).toLowerCase()}`;
  if (name.startsWith("GDOCS_")) return `Google Docs · ${name.slice(6).toLowerCase()}`;
  if (name.startsWith("MICROSOFT_")) return `Microsoft · ${name.slice(10).toLowerCase()}`;
  if (name.startsWith("SLACK_USER_TOKEN_")) return `Slack · ${name.slice(17)}`;
  return name;
}
