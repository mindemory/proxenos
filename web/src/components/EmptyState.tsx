"use client";

import { Check, Copy, FolderX, X, type LucideIcon } from "lucide-react";
import { useState } from "react";

import { FeedSkeleton } from "@/components/Skeleton";
import { useToast } from "@/components/Toasts";

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

/** Explains why a view is empty and which command fills it. */
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
      {command && (
        <div className="mt-1 flex flex-col items-center gap-2">
          <span className="smallcaps">Run this</span>
          <Command block>{command}</Command>
        </div>
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
    <EmptyState icon={FolderX} title="No vault found" command="PROXENOS_VAULT=~/proxenos_vault">
      Looked in <code className="num">{path}</code>. Set PROXENOS_VAULT in the repo&apos;s .env or the environment,
      then reload.
    </EmptyState>
  );
}
