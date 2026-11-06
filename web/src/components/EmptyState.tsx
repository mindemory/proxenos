"use client";

import { Check, Copy, FolderX, X, type LucideIcon } from "lucide-react";
import { useState } from "react";

import { PrimaryButton } from "@/components/connect/parts";
import { FeedSkeleton } from "@/components/Skeleton";
import { useToast } from "@/components/Toasts";
import { MAKE_COMMANDS } from "@/lib/makeCommands";
import { useRunJob } from "@/lib/runJobClient";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  children: React.ReactNode;
  command?: string;
}

/** Faint rings and a few points behind an empty state's icon: a small, quiet illustration. */
function Rings() {
  return (
    <svg viewBox="0 0 160 160" className="absolute inset-0 h-full w-full" aria-hidden="true" fill="none">
      <circle cx="80" cy="80" r="44" stroke="var(--c-line-strong)" strokeOpacity="0.9" />
      <circle cx="80" cy="80" r="64" stroke="var(--c-line)" strokeDasharray="2 5" />
      <circle cx="80" cy="80" r="78" stroke="var(--c-line)" strokeOpacity="0.6" />
      <circle cx="124" cy="80" r="2.5" fill="var(--c-accent)" fillOpacity="0.7" />
      <circle cx="35" cy="58" r="2" fill="var(--c-muted)" fillOpacity="0.6" />
      <circle cx="98" cy="139" r="1.8" fill="var(--c-muted)" fillOpacity="0.5" />
    </svg>
  );
}

/** Explains why a view is empty and which command fills it: a button that runs it, where the page can, and the command for a terminal. */
export function EmptyState({ icon: Icon, title, children, command }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-4 px-6 py-16 text-center">
      <div className="relative flex h-40 w-40 items-center justify-center">
        <Rings />
        <div className="relative flex h-14 w-14 items-center justify-center rounded-2xl border border-accent/25 bg-surface text-accent shadow-card">
          <Icon size={24} strokeWidth={1.75} />
        </div>
      </div>
      <h2 className="title-2 text-2xl">{title}</h2>
      <div className="max-w-md leading-relaxed text-muted">{children}</div>
      {command && Object.hasOwn(MAKE_COMMANDS, command) ? (
        <div className="mt-1 flex flex-col items-center gap-3">
          <MakeIt command={command} />
          <p className="max-w-full text-xs leading-relaxed text-faint">
            From a terminal: <Command>{command}</Command>
          </p>
        </div>
      ) : (
        command && (
          <div className="mt-1 flex flex-col items-center gap-2">
            <span className="smallcaps">From a terminal</span>
            <Command block>{command}</Command>
          </div>
        )
      )}
    </div>
  );
}

/**
 * "Make it now": runs the command in the background through /api/make (which runs only the
 * commands it lists), says what it's doing as it goes, and reloads the page when it's done so the
 * view has what was made. One at a time: while another view's is being made, this waits.
 */
function MakeIt({ command }: { command: string }) {
  const { job, error, start, stop } = useRunJob("/api/make", (ended) => {
    if (ended.state === "done" && ended.command === command) window.location.reload();
  });
  const mine = job?.command === command ? job : null;
  const making = mine?.state === "running";
  const other = job?.state === "running" && !mine;
  const failed = error ?? (mine?.state === "failed" ? mine.message || "It failed." : null);
  return (
    <div className="flex max-w-md flex-col items-center gap-2">
      <div className="flex items-center gap-3">
        <PrimaryButton disabled={making || other} onClick={() => start({ command })}>
          {making ? "Making it…" : "Make it now"}
        </PrimaryButton>
        {making && (
          <button type="button" onClick={stop} className="rounded-full px-2 py-1 text-sm text-muted hover:text-ink">
            Stop
          </button>
        )}
      </div>
      {making && (
        <p className="break-words text-sm text-muted" role="status">
          {mine.message || "Starting…"}
        </p>
      )}
      {other && <p className="text-sm text-muted">Something else is being made. This can start once it&apos;s done.</p>}
      {mine?.state === "done" && (
        <p className="break-words text-sm text-muted">It ran, and the view is still empty: {mine.message || "nothing was made."}</p>
      )}
      {failed && (
        <p className="break-words text-sm text-bad-ink" role="alert">
          {failed}
        </p>
      )}
    </div>
  );
}

/**
 * A shell command, shown the same way everywhere. Clicking it copies it. `block` is the larger
 * form an empty state leads with; inline, it sits in a sentence.
 */
export function Command({ children, block = false }: { children: string; block?: boolean }) {
  const notify = useToast();
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard?.writeText(children).then(
      () => {
        setCopied(true);
        notify("Command copied", "ok");
        window.setTimeout(() => setCopied(false), 1600);
      },
      () => {
        // No clipboard (an insecure context or a denied permission): the text is still there to select.
      },
    );
  };
  const Icon = copied ? Check : Copy;
  if (block) {
    return (
      <button
        type="button"
        onClick={copy}
        title="Copy"
        className="group inline-flex max-w-full items-center gap-3 rounded-xl border border-line-strong bg-surface-2 py-2 pl-3.5 pr-3 text-left transition-colors hover:border-accent/40"
      >
        <span className="text-muted" aria-hidden="true">
          $
        </span>
        <code className="num min-w-0 break-all text-sm text-ink">{children}</code>
        <Icon size={14} className="flex-shrink-0 text-muted group-hover:text-ink" aria-hidden="true" />
        <span className="sr-only">{copied ? "Copied" : "Copy the command"}</span>
      </button>
    );
  }
  return (
    <button
      type="button"
      onClick={copy}
      title="Copy"
      className="num inline rounded-md border border-line-strong bg-surface-2 px-1.5 py-0.5 text-left text-[0.85em] break-all text-ink transition-colors hover:border-accent/40"
    >
      {children}
      <span className="sr-only">{copied ? " (copied)" : " (copy)"}</span>
    </button>
  );
}

/** A quiet one-liner for a block whose data doesn't exist yet. */
export function QuietLine({ children, command }: { children: React.ReactNode; command: string }) {
  return (
    <p className="text-sm leading-relaxed text-muted">
      {children} <Command>{command}</Command>
    </p>
  );
}

/** Errors stay on screen until dismissed; toasts are only for things that worked. */
export function ErrorBanner({ message, onDismiss }: { message: string; onDismiss?: () => void }) {
  return (
    <div
      className="m-4 flex items-start gap-3 rounded-xl border border-bad-line bg-bad-bg p-4 text-sm text-bad-ink"
      role="alert"
    >
      <span className="min-w-0 flex-1 break-words">{message}</span>
      {onDismiss && (
        <button onClick={onDismiss} aria-label="Dismiss" className="-m-0.5 rounded p-0.5 hover:text-ink">
          <X size={16} />
        </button>
      )}
    </div>
  );
}

/** The generic loading state; views with a shape of their own use their skeleton instead. */
export function LoadingRows() {
  return <FeedSkeleton label="Loading" />;
}

/** The usual "no vault" explanation, shared by every view. */
export function NoVault({ path }: { path: string }) {
  return (
    <EmptyState icon={FolderX} title="No vault found">
      Proxenos looked in <code className="num">{path}</code> and found no vault. Choose where it lives in{" "}
      <a href="/setup" className="text-accent hover:underline">
        setup
      </a>{" "}
      (or in Settings, under Vault), then reload this page. From source, you can set PROXENOS_VAULT in .env instead.
    </EmptyState>
  );
}
