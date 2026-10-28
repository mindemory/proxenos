import { cn } from "@/lib/utils";

/** A pill-shaped switch between a view's tabs. */
export function Segmented<T extends string>({
  tabs,
  value,
  onChange,
  label,
}: {
  tabs: { id: T; label: string }[];
  value: T;
  onChange: (t: T) => void;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex min-w-0 bg-surface border border-line p-1 rounded-full">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          aria-pressed={value === t.id}
          className={cn(
            "px-3 sm:px-4 py-1 rounded-full text-sm transition-colors whitespace-nowrap",
            value === t.id ? "bg-surface-2 text-ink" : "text-muted hover:text-ink",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
