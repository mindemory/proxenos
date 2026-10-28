import type { DraftReviews } from "@/lib/types";

/** The roadmap's gate: a channel moves up a level at 80% approved, with light edits. */
export const APPROVAL_GATE = 0.8;

const PARTS = [
  { key: "approved", label: "Approved", color: "var(--c-ok-ink)" },
  { key: "edited", label: "Edited", color: "var(--c-accent)" },
  { key: "discarded", label: "Discarded", color: "var(--c-faint)" },
] as const;

/**
 * How reviewed drafts ended: approved as written, edited, or discarded, as one bar with the
 * approval gate marked on it, and a legend that names every part with its count and share.
 */
export function ReviewBar({ reviews }: { reviews: DraftReviews }) {
  const total = reviews.reviewed;
  const approval = total ? (reviews.approved + reviews.edited) / total : 0;
  const pct = (n: number) => (total ? Math.round((n / total) * 100) : 0);
  const summary = PARTS.map((p) => `${reviews[p.key]} ${p.label.toLowerCase()}`).join(", ");

  return (
    <figure className="space-y-2.5" aria-label={`Drafts reviewed: ${total}. ${summary}.`}>
      <div className="flex items-baseline justify-between gap-3">
        <span className="smallcaps">Review record</span>
        <span className="text-xs text-muted">
          <span className="num text-ink">{Math.round(approval * 100)}%</span> approved · gate{" "}
          <span className="num">{Math.round(APPROVAL_GATE * 100)}%</span>
        </span>
      </div>
      <div className="relative">
        <div className="flex h-2.5 w-full gap-[2px] overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
          {PARTS.map((p) =>
            reviews[p.key] > 0 ? (
              <span
                key={p.key}
                className="h-full first:rounded-l-full last:rounded-r-full"
                style={{ width: `${(reviews[p.key] / total) * 100}%`, background: p.color }}
              />
            ) : null,
          )}
        </div>
        <span
          aria-hidden="true"
          className="absolute -top-1 -bottom-1 w-px bg-ink/70"
          style={{ left: `${APPROVAL_GATE * 100}%` }}
          title="The 80% gate"
        />
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {PARTS.map((p) => (
          <li key={p.key} className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ background: p.color }} aria-hidden="true" />
            {p.label}
            <span className="num text-ink">{reviews[p.key]}</span>
            <span className="num">({pct(reviews[p.key])}%)</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}
