"use client";

import { ArrowLeft, ArrowRight, Check, Plug } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { PrimaryButton } from "@/components/connect/parts";
import { ErrorBanner } from "@/components/EmptyState";
import { Logo, Wordmark } from "@/components/Logo";
import { markEntered } from "@/lib/entry";
import { cloudFor, useSetup } from "@/lib/setupClient";
import type { SetupStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

import { type Apply, CloudWarning, Field, inputClass, ModelChoice, NOT_A_LOGIN, SaidLine, useChange } from "./parts";

const STEPS = ["Your name", "Your vault", "A model", "A first source"];
const DEFAULT_VAULT = "~/proxenos_vault";

/** The first run: your name, where the vault lives, a model, and on to Connect for a first source. */
export function Setup() {
  const { status, error, reload, apply } = useSetup();
  return (
    <main className="flex min-h-dvh flex-col bg-bg">
      <header className="flex items-center gap-2.5 px-5 pt-5 sm:px-8 sm:pt-7">
        <Logo size={24} className="text-accent" />
        <Wordmark className="text-xl" />
        <span className="smallcaps ml-auto text-faint">Local · this Mac only</span>
      </header>
      <div className="mx-auto w-full max-w-xl flex-1 px-4 pb-16 pt-8 sm:pt-14">
        {status ? (
          <Flow status={status} apply={apply} onReload={reload} />
        ) : error ? (
          <ErrorBanner message={`Couldn't read the settings: ${error}`} />
        ) : (
          <div className="card space-y-4 p-6" aria-busy="true" aria-label="Loading the settings">
            <span className="skeleton block h-4 w-24" />
            <span className="skeleton block h-7 w-3/4" />
            <span className="skeleton block h-10 w-full" />
          </div>
        )}
      </div>
    </main>
  );
}

function Progress({ step }: { step: number }) {
  return (
    <div className="space-y-2.5">
      <p className="smallcaps text-faint">
        Step <span className="num">{step + 1}</span> of <span className="num">{STEPS.length}</span> · {STEPS[step]}
      </p>
      <ol className="grid grid-cols-4 gap-1.5" aria-hidden="true">
        {STEPS.map((label, i) => (
          <li key={label} className={cn("h-1 rounded-full", i <= step ? "bg-accent" : "bg-line-strong")} />
        ))}
      </ol>
    </div>
  );
}

function Back({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1.5 rounded-full px-2 py-1.5 text-sm text-muted hover:text-ink"
    >
      <ArrowLeft size={14} aria-hidden="true" />
      Back
    </button>
  );
}

function Flow({ status, apply, onReload }: { status: SetupStatus; apply: Apply; onReload: () => void }) {
  const router = useRouter();
  // A first run starts at the start; a reload part way through picks up at the model, or the end.
  const [step, setStep] = useState(() => (status.needed ? 0 : status.model.kind === "none" ? 2 : 3));
  const [name, setName] = useState(status.settings.name.value ?? "");
  const [vault, setVault] = useState(status.settings.vault.value ?? DEFAULT_VAULT);
  const { busy, said, run, clear } = useChange(apply);
  const go = (next: number) => {
    clear();
    setStep(next);
    window.scrollTo({ top: 0 });
  };
  const enter = (view?: string) => {
    markEntered();
    router.push(view ? `/app?view=${view}` : "/app");
  };

  const body = (() => {
    switch (step) {
      case 0:
        return (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim()) go(1);
            }}
            className="space-y-6"
          >
            <Heading title="What should Proxenos call you?">
              It&apos;s the name in the notes and the picture of you that Proxenos writes from your records. Your first name is enough.
            </Heading>
            <Field label="Your name">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Ana"
                maxLength={100}
                autoFocus
                className={inputClass}
                {...NOT_A_LOGIN}
              />
            </Field>
            <div className="flex justify-end">
              <PrimaryButton type="submit" disabled={!name.trim()}>
                Continue
                <ArrowRight size={14} aria-hidden="true" />
              </PrimaryButton>
            </div>
          </form>
        );
      case 1:
        return (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              run({ settings: { name: name.trim(), vault: vault.trim() } }).then((ok) => ok && go(2));
            }}
            className="space-y-6"
          >
            <Heading title="Where should your vault live?">
              The vault is one folder on this Mac that holds everything: what Proxenos reads from your accounts, its notes, and the drafts
              it writes. Nothing in it leaves the computer unless you send it.
            </Heading>
            <Field label="Folder" hint="Type its path. Proxenos makes the folder if it isn't there yet.">
              <input
                value={vault}
                onChange={(e) => setVault(e.target.value)}
                placeholder={DEFAULT_VAULT}
                className={cn(inputClass, "num")}
                {...NOT_A_LOGIN}
              />
            </Field>
            <CloudWarning where={cloudFor(vault, status.home)} />
            <SaidLine said={said?.ok ? null : said} />
            <div className="flex items-center justify-between gap-3">
              <Back onClick={() => go(0)} />
              <PrimaryButton type="submit" disabled={busy || !vault.trim()}>
                {busy ? "Saving…" : "Save and continue"}
                <ArrowRight size={14} aria-hidden="true" />
              </PrimaryButton>
            </div>
          </form>
        );
      case 2:
        return (
          <div className="space-y-6">
            <Heading title="Which model should draft for you?">
              Proxenos uses a model to write its notes and draft your next steps. You can skip this: your sources still sync and search
              still works, but nothing is drafted until you pick one in Settings.
            </Heading>
            <ModelChoice status={status} apply={apply} onReload={onReload} />
            <div className="flex items-center justify-between gap-3 border-t border-line pt-5">
              <Back onClick={() => go(1)} />
              {status.model.kind === "none" ? (
                <button type="button" onClick={() => go(3)} className="rounded-full px-3 py-1.5 text-sm text-muted hover:text-ink">
                  Skip for now
                </button>
              ) : (
                <PrimaryButton onClick={() => go(3)}>
                  Continue
                  <ArrowRight size={14} aria-hidden="true" />
                </PrimaryButton>
              )}
            </div>
          </div>
        );
      default:
        return (
          <div className="space-y-6">
            <Heading title="Connect a first source">
              Proxenos reads only what you connect: your mail, WhatsApp, Slack, a download of your data. Start with one; the rest can come
              any time from Connect.
            </Heading>
            <ul className="divide-y divide-line rounded-xl border border-line text-sm">
              <Done label="Name" value={status.settings.name.value} />
              <Done label="Vault" value={status.vault.exists ? status.vault.path : null} mono />
              <Done
                label="Model"
                value={status.model.kind === "none" ? null : status.model.name}
                mono
                missing="Skipped: pick one in Settings"
              />
            </ul>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <Back onClick={() => go(2)} />
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" onClick={() => enter()} className="rounded-full px-3 py-1.5 text-sm text-muted hover:text-ink">
                  Go to Proxenos
                </button>
                <PrimaryButton onClick={() => enter("connect")}>
                  <Plug size={14} aria-hidden="true" />
                  Open Connect
                </PrimaryButton>
              </div>
            </div>
          </div>
        );
    }
  })();

  return (
    <div className="space-y-6">
      <Progress step={step} />
      <section key={step} className="card screen-in p-5 sm:p-7">
        {body}
      </section>
      <p className="text-center text-xs leading-relaxed text-faint">
        Saved {status.savesTo === ".env" ? "in the repo's .env" : <span className="num">{status.settingsFile}</span>}. Change any of it
        later in Settings.
      </p>
    </div>
  );
}

function Heading({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <h1 className="title-2 text-2xl">{title}</h1>
      <p className="leading-relaxed text-muted">{children}</p>
    </div>
  );
}

function Done({
  label,
  value,
  mono = false,
  missing = "Not set",
}: {
  label: string;
  value: string | null;
  mono?: boolean;
  missing?: string;
}) {
  return (
    <li className="flex items-center gap-3 px-3.5 py-2.5">
      <span
        className={cn(
          "flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full",
          value ? "bg-ok-bg text-ok-ink" : "bg-surface-2 text-faint",
        )}
      >
        {value ? <Check size={12} aria-hidden="true" /> : <span className="h-1 w-1 rounded-full bg-current" aria-hidden="true" />}
      </span>
      <span className="w-14 flex-shrink-0 text-muted">{label}</span>
      <span className={cn("min-w-0 truncate", value ? "text-ink" : "text-muted", mono && value && "num")}>{value ?? missing}</span>
    </li>
  );
}
