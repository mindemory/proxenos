import { APPROVAL_GATE } from "@/components/charts/ReviewBar";
import { REVIEW_WINDOW_DAYS } from "@/lib/drafts";
import type { DraftCloseness, DraftReviews } from "@/lib/types";
import { cn } from "@/lib/utils";

const pct = (n: number, of: number) => Math.round((n / of) * 100);

/**
 * How the drafts have fared: the counts, and the rate the roadmap's gate looks at, the share of
 * reviewed drafts approved with light edits. Each count is one draft's latest word; a sent draft
 * is also counted as approved.
 */
export function TrackRecord({ record, closeness }: { record: DraftReviews; closeness?: DraftCloseness | null }) {
  const stats = [
    ["Approved", record.approved],
    ["Edited", record.edited],
    ["Discarded", record.discarded],
    ["Sent", record.sent],
  ] as const;
  const rate = record.reviewed ? pct(record.approved + record.edited, record.reviewed) : null;
  const gate = Math.round(APPROVAL_GATE * 100);

  return (
    <section
      aria-label="Track record"
      className="px-4 sm:px-6 py-3 border-b border-line flex flex-wrap items-baseline gap-x-6 gap-y-2"
    >
      <h2 className="smallcaps">Track record</h2>
      <dl className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
        {stats.map(([label, n]) => (
          <div key={label} className="flex items-baseline gap-1.5">
            <dt className="text-muted">{label}</dt>
            <dd className="num text-ink">{n}</dd>
          </div>
        ))}
      </dl>
      <p
        className="text-sm text-muted sm:ml-auto"
        title="Approved or edited, out of every draft you've approved, edited or discarded. The log doesn't record how much an edit changed, so any edit counts as light."
      >
        Approved with light edits{" "}
        {rate === null ? (
          "not measured yet"
        ) : (
          <span className={cn("num", rate >= gate ? "text-ok-ink" : "text-ink")}>{rate}%</span>
        )}{" "}
        <span className="text-faint">(gate {gate}%)</span>
        <span className="mx-1.5 text-faint" aria-hidden="true">
          ·
        </span>
        Last {REVIEW_WINDOW_DAYS} days{" "}
        {record.recentReviewed === 0 ? (
          "no reviews"
        ) : (
          <span className="num text-ink">
            {record.recentAccepted} of {record.recentReviewed} ({pct(record.recentAccepted, record.recentReviewed)}%)
          </span>
        )}
      </p>
      {closeness && (
        <p
          className="w-full text-sm text-muted"
          title="For each reply drafted for a chat: how much of the draft was still there in what you then sent in that chat, from 0% (rewritten) to 100% (sent as written)."
        >
          Replies sent as drafted{" "}
          <span className="num text-ink">
            {closeness.sentAsIs} of {closeness.measured}
          </span>
          {Object.entries(closeness.bySource).map(([source, s]) => (
            <span key={source}>
              <span className="mx-1.5 text-faint" aria-hidden="true">
                ·
              </span>
              {source} <span className="num text-ink">{Math.round(s.mean * 100)}%</span> close{" "}
              <span className="text-faint">({s.n})</span>
            </span>
          ))}
        </p>
      )}
    </section>
  );
}
