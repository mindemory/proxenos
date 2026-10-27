import type { LucideIcon } from "lucide-react";

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
      <div className="w-16 h-16 rounded-2xl bg-primary/20 text-yellow-700 flex items-center justify-center">
        <Icon size={28} strokeWidth={2.5} />
      </div>
      <h2 className="text-xl font-bold text-text-primary">{title}</h2>
      <div className="text-text-secondary max-w-md leading-relaxed">{children}</div>
      {command && (
        <code className="bg-text-primary text-white px-3 py-1.5 rounded-lg text-sm font-mono break-all">{command}</code>
      )}
    </div>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="m-4 p-4 rounded-xl border border-red-200 bg-red-50 text-red-700 text-sm" role="alert">
      {message}
    </div>
  );
}

export function LoadingRows() {
  return (
    <div className="divide-y divide-gray-100" aria-busy="true">
      {[0, 1, 2].map((i) => (
        <div key={i} className="p-6 flex gap-4">
          <div className="w-12 h-12 rounded-full bg-gray-200 animate-pulse flex-shrink-0" />
          <div className="flex-1 space-y-3">
            <div className="h-4 w-1/3 bg-gray-200 rounded animate-pulse" />
            <div className="h-5 w-full bg-gray-200 rounded animate-pulse" />
            <div className="h-24 w-full bg-gray-100 rounded-xl animate-pulse" />
          </div>
        </div>
      ))}
    </div>
  );
}
