import { FolderX, X, type LucideIcon } from "lucide-react";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  children: React.ReactNode;
  command?: string;
}

/** Explains why a view is empty and which command fills it. */
export function EmptyState({ icon: Icon, title, children, command }: EmptyStateProps) {
  return (
    <div className="px-6 py-16 flex flex-col items-center text-center gap-4">
      <div className="w-14 h-14 rounded-2xl bg-accent/10 border border-accent/20 text-accent flex items-center justify-center">
        <Icon size={24} strokeWidth={2} />
      </div>
      <h2 className="font-display text-2xl text-ink">{title}</h2>
      <div className="text-muted max-w-md leading-relaxed">{children}</div>
      {command && <Command>{command}</Command>}
    </div>
  );
}

/** A shell command, shown the same way everywhere. */
export function Command({ children }: { children: React.ReactNode }) {
  return (
    <code className="num bg-surface-2 border border-line-strong text-ink px-2 py-0.5 rounded-md text-[0.85em] break-all">
      {children}
    </code>
  );
}

/** A quiet one-liner for a block whose data doesn't exist yet. */
export function QuietLine({ children, command }: { children: React.ReactNode; command: string }) {
  return (
    <p className="text-sm text-muted leading-relaxed">
      {children} <Command>{command}</Command>
    </p>
  );
}

/** Errors stay on screen until dismissed; toasts are only for things that worked. */
export function ErrorBanner({ message, onDismiss }: { message: string; onDismiss?: () => void }) {
  return (
    <div
      className="m-4 p-4 rounded-xl border border-bad-line bg-bad-bg text-bad-ink text-sm flex items-start gap-3"
      role="alert"
    >
      <span className="flex-1 min-w-0 break-words">{message}</span>
      {onDismiss && (
        <button onClick={onDismiss} aria-label="Dismiss" className="p-0.5 -m-0.5 rounded hover:text-ink">
          <X size={16} />
        </button>
      )}
    </div>
  );
}

export function LoadingRows() {
  return (
    <div className="divide-y divide-line" aria-busy="true">
      {[0, 1, 2].map((i) => (
        <div key={i} className="p-6 flex gap-4">
          <div className="w-9 h-9 rounded-full bg-surface-2 animate-pulse flex-shrink-0" />
          <div className="flex-1 space-y-3">
            <div className="h-3.5 w-1/3 bg-surface-2 rounded animate-pulse" />
            <div className="h-4 w-full bg-surface-2 rounded animate-pulse" />
            <div className="h-20 w-full bg-surface rounded-xl animate-pulse" />
          </div>
        </div>
      ))}
    </div>
  );
}

/** The usual "no vault" explanation, shared by every view. */
export function NoVault({ path }: { path: string }) {
  return (
    <EmptyState icon={FolderX} title="No vault found" command="TWIN_VAULT=~/twin_vault">
      Looked in <code className="num">{path}</code>. Set TWIN_VAULT in the repo&apos;s .env or the environment, then
      reload.
    </EmptyState>
  );
}
