"use client";

import { Check, Cpu, FileUp, KeyRound, RefreshCw, TriangleAlert, X } from "lucide-react";
import { useEffect, useState } from "react";

import { PrimaryButton, Steps } from "@/components/connect/parts";
import { Command } from "@/components/EmptyState";
import { Segmented } from "@/components/layout/Segmented";
import { googleClientFrom } from "@/lib/googleClient";
import { useRunJob } from "@/lib/runJobClient";
import { hostedModels } from "@/lib/setupClient";
import type { HostedModels, HostedProvider, LocalModel, SetupChange, SettingOrigin, SetupStatus } from "@/lib/types";
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
        Your records would leave this computer. A folder straight in your home folder, like ~/proxenos_vault, stays here.
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
  if (from === "app") return "from this app";
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
            Using <span className="num text-ink">{model.label}</span> on this computer
            {model.via === "server" ? (
              <>
                , through the server at <span className="num">{status.server.url}</span>
              </>
            ) : model.via === "app" ? (
              ", run by Proxenos itself"
            ) : (
              ", through Ollama"
            )}
            .
          </span>
        ) : model.kind === "api" ? (
          <span>
            Using <span className="num text-ink">{model.label}</span> through {PROVIDERS[model.provider ?? "anthropic"].label}, with your key.
          </span>
        ) : (
          "No model yet."
        )}
      </p>
      <Segmented
        label="Where the model runs"
        tabs={[
          { id: "local", label: "On this computer" },
          { id: "api", label: "API key" },
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
  const [via, setVia] = useState<"app" | "ollama" | "server">(
    status.model.via ?? (status.here.capable ? "app" : status.server.running && !status.ollama.running ? "server" : "ollama"),
  );
  return (
    <div className="space-y-3">
      <p className="text-sm leading-relaxed text-muted">
        A model that runs on this computer. What you write to it never leaves, and you need no account or key.{" "}
        {status.here.capable && "In Proxenos needs nothing else. Ollama and LM Studio are free apps that run models too, if you already use one."}{" "}
        {status.computer.advice}
      </p>
      <Segmented
        label="What runs the model"
        tabs={[
          ...(status.here.capable ? [{ id: "app" as const, label: "In Proxenos" }] : []),
          { id: "ollama" as const, label: "Ollama" },
          { id: "server" as const, label: "LM Studio and others" },
        ]}
        value={via}
        onChange={setVia}
      />
      {via === "app" ? (
        <AppModel status={status} onReload={onReload} />
      ) : via === "ollama" ? (
        <OllamaModel status={status} apply={apply} onReload={onReload} />
      ) : (
        <ServerModel status={status} apply={apply} onReload={onReload} />
      )}
    </div>
  );
}

/**
 * A model Proxenos runs itself, with nothing else to install (an Apple-silicon Mac with mlx-lm, as
 * the desktop app has): the small one to start with, and, when this computer has the memory, the
 * bigger one to write with, downloaded in the background after it. The weights come from Hugging
 * Face; nothing of yours goes there.
 */
function AppModel({ status, onReload }: { status: SetupStatus; onReload: () => void }) {
  const { small, big } = status.here;
  const download = useDownload(onReload);
  const using = status.model.via === "app";
  const gb = (bytes: number) => `${Math.round(bytes / 1e9)} GB`;
  return (
    <div className="space-y-3 rounded-xl border border-line-strong bg-surface-2/60 p-3.5">
      {!small.ready || !using ? (
        <>
          <PrimaryButton disabled={download.running} onClick={() => download.start(small.repo, "starter", true)}>
            {small.ready ? `Use ${small.name}` : `Download the model (about ${gb(small.bytes)})`}
          </PrimaryButton>
          <p className="text-xs leading-relaxed text-faint">
            {small.name} runs inside Proxenos on this Mac. You install no other app and make no account. It downloads once from Hugging
            Face, a site that shares open models, and nothing of yours is sent there. It can take a while on a slow connection. You&apos;ll
            see &quot;Using {small.name}&quot; here when it&apos;s ready.
            {big.fits && ` Then you can also get ${big.name} (about ${gb(big.bytes)}), which writes better.`}
          </p>
        </>
      ) : (
        <>
          <p className="text-sm leading-relaxed text-muted">
            <span className="num text-ink">{small.name}</span> is downloaded and runs inside Proxenos.
          </p>
          {big.fits && !(big.ready && big.serving) && (
            <div className="space-y-2">
              <p className="text-sm leading-relaxed text-muted">
                A bigger model writes better drafts. Get {big.name} (about {gb(big.bytes)}) in the background. Proxenos keeps using{" "}
                <span className="num text-ink">{status.model.label}</span> until it&apos;s ready, and {small.name} goes on doing the light jobs.
              </p>
              <PrimaryButton disabled={download.running} onClick={() => download.start(big.repo, "main", true)}>
                Get {big.name}
              </PrimaryButton>
            </div>
          )}
        </>
      )}
      <Downloading download={download} />
    </div>
  );
}

function OllamaModel({ status, apply, onReload }: { status: SetupStatus; apply: Apply; onReload: () => void }) {
  const { running, models, suggested } = status.ollama;
  const { busy, said, run } = useChange(apply);
  const { starter, get, upgrade } = status.computer;
  const download = useDownload(onReload);
  return (
    <div className="space-y-3">
      {!running ? (
        <Missing onReload={onReload} state="Ollama isn't running.">
          <li>
            Download Ollama from{" "}
            <a href="https://ollama.com/download" target="_blank" rel="noreferrer" className="text-accent hover:underline">
              ollama.com/download
            </a>{" "}
            and install it.
          </li>
          <li>Open Ollama.</li>
          <li>Come back here and press <strong>Check again</strong>. You&apos;ll see a button to download a model.</li>
        </Missing>
      ) : !models.length ? (
        <div className="space-y-3 rounded-xl border border-line-strong bg-surface-2/60 p-3.5">
          {starter || get ? (
            <>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <PrimaryButton disabled={download.running} onClick={() => download.start((starter ?? get) as string, "starter")}>
                  Download {starter ?? get} (about {approx(starter ?? get)})
                </PrimaryButton>
                {starter && get && (
                  <button
                    type="button"
                    disabled={download.running}
                    onClick={() => download.start(get, "starter")}
                    className="text-sm text-muted transition-colors hover:text-ink disabled:opacity-60"
                  >
                    or {get} (about {approx(get)}) for better writing
                  </button>
                )}
              </div>
              <p className="text-xs leading-relaxed text-faint">
                Ollama is running but has no model yet. Press the button to download one from Ollama&apos;s library. Proxenos uses it as soon
                as it&apos;s here.
              </p>
            </>
          ) : (
            <p className="text-sm leading-relaxed text-muted">
              Ollama is running, but no model Proxenos suggests fits this computer&apos;s memory. Use the API key tab instead.
            </p>
          )}
          <Downloading download={download} />
        </div>
      ) : (
        <>
          <ModelPicker
            models={models}
            suggested={suggested}
            current={status.model.via === "ollama" ? status.model.name : null}
            rule={status.computer.rule}
            busy={busy}
            onUse={(name) => run({ ollama: name })}
          />
          {(upgrade || download.running) && (
            <div className="space-y-2 rounded-xl border border-line-strong bg-surface-2/60 p-3.5">
              {upgrade && (
                <>
                  <p className="text-sm leading-relaxed text-muted">
                    A bigger model writes better drafts. Get {upgrade} (about {approx(upgrade)}) in the background. Proxenos keeps using{" "}
                    <span className="num text-ink">{status.model.label}</span> until it&apos;s ready.
                  </p>
                  <PrimaryButton disabled={download.running} onClick={() => download.start(upgrade, "main")}>
                    Get {upgrade}
                  </PrimaryButton>
                </>
              )}
              <Downloading download={download} />
            </div>
          )}
        </>
      )}
      <SaidLine said={said} />
    </div>
  );
}

/** About how big a model Proxenos suggests is to download: the sizes proxenos.machine uses, so every sentence agrees. */
function approx(name: string | null): string {
  return (name && { "gemma4:e4b": "7 GB", "gemma4:26b": "17 GB" }[name]) || "a few GB";
}

/** A model download the page started, followed by its last line; `onDone` is told when it finishes. */
function useDownload(onDone: () => void) {
  const [asked, setAsked] = useState(false);
  const { job, error, start, stop } = useRunJob("/api/setup/pull", (ended) => {
    if (ended.state === "done") onDone();
  });
  return {
    job,
    error,
    asked,
    running: job?.state === "running",
    /** `here`: a model Proxenos runs itself, named by its Hugging Face repo, not one of Ollama's. */
    start: (name: string, as: "starter" | "main", here = false) => {
      setAsked(true);
      return start(here ? { repo: name, as } : { name, as });
    },
    stop,
  };
}

/** How far a download is along (with Stop), or why it ended, once this page started it. */
function Downloading({ download }: { download: ReturnType<typeof useDownload> }) {
  const { job, error, asked, stop } = download;
  const problem = error ?? (asked && job && (job.state === "failed" || job.state === "stopped") ? job.message : null);
  return (
    <>
      {job?.state === "running" && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <p className="num min-w-0 break-words text-sm text-ink" role="status">
            {job.message || "Starting…"}
          </p>
          <button type="button" onClick={stop} className="rounded-full border border-line-strong px-3 py-1 text-sm text-muted hover:text-ink">
            Stop
          </button>
        </div>
      )}
      {problem && (
        <p className="flex items-start gap-1.5 text-sm leading-relaxed text-bad-ink" role="alert">
          <X size={15} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
          <span className="min-w-0 break-words">{problem}</span>
        </p>
      )}
    </>
  );
}

/** A model another app serves on this computer through OpenAI's API: LM Studio, llama.cpp's llama-server, Jan, LocalAI or vLLM. */
function ServerModel({ status, apply, onReload }: { status: SetupStatus; apply: Apply; onReload: () => void }) {
  const { running, models, suggested, url, error, context } = status.server;
  const { busy, said, run } = useChange(apply);
  return (
    <div className="space-y-3">
      <p className="text-sm leading-relaxed text-muted">
        Use this if an app like LM Studio, llama-server, Jan, LocalAI or vLLM already runs a model on this computer and shares it with
        other programs. Load the model there with a context length of <span className="num">{context.toLocaleString("en-US")}</span>{" "}
        (how much text it can read at once), so Proxenos&apos;s longest prompts fit.
      </p>
      <ServerAddress status={status} apply={apply} />
      {error ? null : !running || !models.length ? (
        <Missing onReload={onReload} state={running ? `The server at ${url} has no model loaded.` : `Nothing answers at ${url}.`}>
          {!running && <li>Start its server. In LM Studio, open the <strong>Developer</strong> tab and turn the server on.</li>}
          <li>Load a model there, with a context length of {context.toLocaleString("en-US")}.</li>
          <li>Come back here and press <strong>Check again</strong>.</li>
          {!running && (
            <li>
              Using llama-server? Type http://127.0.0.1:8080/v1 as the server address above, then run this in a terminal:{" "}
              <Command>{`llama-server -m MODEL.gguf -c ${context} --port 8080`}</Command>
            </li>
          )}
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

const PROVIDERS: Record<
  HostedProvider,
  { label: string; secret: string; site: string; href: string; start: string; tell: React.ReactNode }
> = {
  anthropic: {
    label: "Anthropic",
    secret: "ANTHROPIC_API_KEY",
    site: "console.anthropic.com",
    href: "https://console.anthropic.com/settings/keys",
    start: "sk-ant-…",
    tell: "Claude, with a personal key kept apart from any work account.",
  },
  openai: {
    label: "OpenAI",
    secret: "OPENAI_API_KEY",
    site: "platform.openai.com",
    href: "https://platform.openai.com/api-keys",
    start: "sk-…",
    tell: "A ChatGPT subscription doesn't include this. The key is billed per use. OpenAI doesn't train on what's sent through its API by default, and keeps it up to 30 days to watch for abuse.",
  },
  gemini: {
    label: "Google Gemini",
    secret: "GEMINI_API_KEY",
    site: "aistudio.google.com",
    href: "https://aistudio.google.com/apikey",
    start: "AIza…",
    tell: "A Gemini app subscription doesn't include this. The key is billed per use.",
  },
};

/** Which provider the model for what you wait on is at, from the ask model setting, else the main model's. */
function hostedNow(status: SetupStatus): HostedProvider {
  const ask = status.settings.ask_model.value ?? "";
  if (ask.startsWith("openai:")) return "openai";
  if (ask.startsWith("gemini:")) return "gemini";
  return status.model.provider ?? "anthropic";
}

/** A hosted model: Anthropic's, OpenAI's or Google's, with your own key. OpenAI's and Gemini's list their own models to pick from. */
function ApiKey({ status, apply }: { status: SetupStatus; apply: Apply }) {
  const [provider, setProvider] = useState<HostedProvider>(() => hostedNow(status));
  const [key, setKey] = useState("");
  const [listed, setModels] = useState<HostedModels | null>(null);
  const [pick, setPick] = useState("");
  const { busy, said, run } = useChange(apply);
  const info = PROVIDERS[provider];
  const saved = status.secrets.find((s) => s.name === info.secret);
  const models = listed?.provider === provider ? listed : null; // another provider's list isn't this one's
  const keySaved = !!saved?.set;
  const where = status.savesTo === ".env" ? "the repo's .env" : status.keychain ? `the ${status.secretStore}` : "your settings";

  // A key already saved: ask its provider for the models to pick from.
  useEffect(() => {
    if (provider === "anthropic" || !keySaved) return;
    let current = true;
    hostedModels(provider).then(
      (m) => {
        if (!current) return;
        setModels(m);
        setPick(m.chosen ?? m.suggested ?? m.names[0] ?? "");
      },
      () => {}, // the key tells why when it's checked again
    );
    return () => {
      current = false;
    };
  }, [provider, keySaved]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    run(provider === "anthropic" ? { key } : { key, provider }).then((ok) => {
      if (!ok) return;
      setKey("");
      if (provider !== "anthropic") hostedModels(provider).then((m) => {
        setModels(m);
        setPick(m.chosen ?? m.suggested ?? m.names[0] ?? "");
      }, () => {});
    });
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <Segmented
        label="Which provider"
        tabs={[
          { id: "anthropic", label: "Anthropic" },
          { id: "openai", label: "OpenAI" },
          { id: "gemini", label: "Google Gemini" },
        ]}
        value={provider}
        onChange={(p) => {
          setProvider(p);
          setKey("");
        }}
      />
      <p className="text-sm leading-relaxed text-muted">
        A key is a password-like code from {info.label} that lets Proxenos use its models. {info.tell}
      </p>
      <Steps>
        <li>
          Open{" "}
          <a href={info.href} target="_blank" rel="noreferrer" className="text-accent hover:underline">
            {info.site}
          </a>{" "}
          and sign in.
        </li>
        <li>Make a new key and copy it.</li>
        <li>
          Paste it below and press <strong>Check and save</strong>.
        </li>
      </Steps>
      <p className="text-sm leading-relaxed text-muted">
        {info.label}&apos;s model then answers what you wait on (Ask, Think, errands, calls), and that text is sent to {info.label} under
        your key. The rest stays on the model on this computer, if you have one.
      </p>
      {provider === "gemini" && (
        <div
          className="flex items-start gap-2.5 rounded-xl border border-warn-line bg-warn-bg px-3.5 py-2.5 text-sm text-warn-ink"
          role="status"
        >
          <TriangleAlert size={16} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
          <span className="leading-relaxed">
            On Google&apos;s free tier, Google may use what&apos;s sent to improve its products. That includes other people&apos;s
            messages that Proxenos sends. Use a key with billing turned on, or a model on this computer.
          </span>
        </div>
      )}
      <div className="grid gap-2.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
        <Field label={saved?.set ? "Replace the key" : "API key"}>
          <input
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder={saved?.set ? `Saved ${originLabel(saved.from, status.secretStore)}` : info.start}
            className={inputClass}
            {...NOT_A_LOGIN}
          />
        </Field>
        <PrimaryButton type="submit" disabled={busy || !key.trim()}>
          <KeyRound size={14} aria-hidden="true" />
          {busy ? "Checking…" : "Check and save"}
        </PrimaryButton>
      </div>
      {provider !== "anthropic" && models && models.names.length > 0 && (
        <div className="grid gap-2.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
          <Field label="Model" hint={models.suggested ? `${models.suggested} is suggested. These are the models ${info.label} lists for your key.` : undefined}>
            <select value={pick} onChange={(e) => setPick(e.target.value)} className={cn(inputClass, "num")}>
              {models.names.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </Field>
          <PrimaryButton disabled={busy || !pick || pick === models.chosen} onClick={() => run({ hosted_model: `${provider}:${pick}` })}>
            {pick === models.chosen ? "In use" : "Use this model"}
          </PrimaryButton>
        </div>
      )}
      <p className="text-xs leading-relaxed text-muted">
        Proxenos asks {info.label} once {provider === "anthropic" ? "whether the key works" : "which models the key can use"}, then keeps it
        in {where}. This page never shows it again. You&apos;ll see &quot;The key works&quot; here when it&apos;s saved.
      </p>
      <SaidLine said={said} />
    </form>
  );
}

/** A secret's name in the page's words. */
export function secretLabel(name: string): string {
  const fixed: Record<string, string> = {
    ANTHROPIC_API_KEY: "Anthropic API key",
    OPENAI_API_KEY: "OpenAI API key",
    GEMINI_API_KEY: "Gemini API key",
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
    BRAVE_SEARCH_KEY: "Brave Search key (looking people up)",
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

/**
 * "Load the file you downloaded from Google": the JSON Google's console gives for an OAuth client.
 * It's read here, in the browser; only its ID and secret go on, in the request's body, and neither
 * is shown or kept in the page.
 */
export function GoogleClientFile({ save, label = "Load the file you downloaded from Google" }: { save: Apply; label?: string }) {
  const { busy, said, run } = useChange(save);
  const [problem, setProblem] = useState<string | null>(null);
  const load = async (file: File | undefined) => {
    setProblem(null);
    if (!file) return;
    const client = file.size <= 64 * 1024 ? googleClientFrom(await file.text().catch(() => "")) : null;
    if (!client) setProblem("That isn't the sign-in client file from Google. It should hold a client_id and a client_secret. Download it again from Google Cloud and try once more.");
    else await run({ google_client: client });
  };
  return (
    <div className="space-y-1.5">
      <label
        className={cn(
          "inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-line-strong px-3 py-1.5 text-[0.8125rem] text-muted transition-colors hover:text-ink focus-within:border-accent/60",
          busy && "pointer-events-none opacity-50",
        )}
      >
        <FileUp size={13} aria-hidden="true" />
        {busy ? "Saving…" : label}
        <input
          type="file"
          accept=".json,application/json"
          className="sr-only"
          disabled={busy}
          onChange={(e) => {
            const input = e.currentTarget;
            load(input.files?.[0]).finally(() => {
              input.value = "";
            });
          }}
        />
      </label>
      {problem && (
        <p className="text-sm text-bad-ink" role="alert">
          {problem}
        </p>
      )}
      <SaidLine said={said} />
    </div>
  );
}
