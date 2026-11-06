"use client";

import { useId, useState } from "react";
import {
  ArrowUpRight,
  BriefcaseBusiness,
  CalendarClock,
  Check,
  ChevronDown,
  FileText,
  MessageSquareReply,
  PenLine,
  Route,
  Search,
  UserRound,
  X,
} from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { Command, EmptyState, ErrorBanner, NoVault } from "@/components/EmptyState";
import { ProseSkeleton } from "@/components/Skeleton";
import { useToast } from "@/components/Toasts";
import { errandFromGoal } from "@/lib/errandsClient";
import { daysBetween, formatDateTime, localDay, plural, shortDate, timeAgo } from "@/lib/format";
import { useJobs } from "@/lib/jobsClient";
import { JOB_SOURCES, JOB_STATUSES, type Job, type JobAction, type JobSource, type JobStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const SOURCES: Record<JobSource, string> = {
  linkedin: "LinkedIn",
  workatastartup: "Work at a Startup",
  recruiter: "Recruiters",
  boards: "Job boards",
  lists: "Lists",
  slack: "Slack",
  ask: "Shared to Ask",
};

const STATUSES: Record<JobStatus, string> = {
  new: "New",
  interested: "Interested",
  applied: "Applied",
  interviewing: "Interviewing",
  closed: "Closed",
};

const VERDICTS = {
  apply: { label: "Apply", tone: "border-ok-line bg-ok-bg text-ok-ink" },
  maybe: { label: "Maybe", tone: "border-accent/40 bg-accent/10 text-accent" },
  skip: { label: "Skip", tone: "border-line-strong bg-surface-2 text-muted" },
} as const;

const ROUTES: Record<string, string> = {
  apply: "Apply on the job's page",
  reply: "Reply to their message",
  note: "A short note to whoever posted it",
  referral: "Through someone you know there",
  email: "Apply by email",
};

/** Which jobs the status filter shows: the open ones (new and interested), all, or one status. */
type StatusFilter = "open" | "all" | JobStatus;

function stepLabel(step: NonNullable<Job["step"]>): string {
  const to = step.to || "them";
  switch (step.kind) {
    case "reply":
      return `A reply to ${to}`;
    case "note":
      return `A note to ${to}`;
    case "intro":
      return `Asking ${to} for an introduction`;
    case "email":
      return `An email to ${to}, applying`;
    default:
      return "The opening of a cover letter";
  }
}

/** When it's due, said plainly, and whether that's soon. */
function due(deadline: string, now: string): { text: string; soon: boolean; passed: boolean } {
  const days = daysBetween(localDay(now), deadline);
  const when = days === 0 ? "today" : days === 1 ? "tomorrow" : days > 1 ? `in ${plural(days, "day")}` : "passed";
  return { text: `Due ${shortDate(`${deadline}T12:00:00`, now)}, ${when}`, soon: days >= 0 && days <= 7, passed: days < 0 };
}

function where(link: string): string {
  try {
    const host = new URL(link).hostname;
    if (host.endsWith("workatastartup.com")) return "Answer on Work at a Startup";
    if (host.endsWith("linkedin.com")) return "Answer on LinkedIn";
  } catch {
    // Not a link after all: the generic label.
  }
  return "Answer where they wrote";
}

function OutLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 rounded-full border border-line-strong px-3 py-1.5 text-[0.8125rem] leading-none text-muted hover:border-accent/40 hover:text-accent"
    >
      {children}
      <ArrowUpRight size={14} aria-hidden="true" />
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-0.5 sm:grid-cols-[9rem_1fr] sm:gap-3">
      <dt className="eyebrow">{label}</dt>
      <dd className="min-w-0 break-words text-sm leading-relaxed text-ink/90">{children}</dd>
    </div>
  );
}

interface JobRowProps {
  job: Job;
  now: string;
  flash: boolean;
  onMark: (job: Job, action: JobAction) => void;
  onDraft?: (id: string) => void;
  onErrand: (goal: string) => void;
  onMemory?: (query: string, id?: string) => void;
}

/** One job: what and where, the verdict and why, its status, and, opened, how to go about it. */
function JobRow({ job, now, flash, onMark, onDraft, onErrand, onMemory }: JobRowProps) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const verdict = job.verdict ? VERDICTS[job.verdict] : null;
  const deadline = job.deadline ? due(job.deadline, now) : null;
  const facts = [job.place, job.mode, job.pay].filter(Boolean).join(" · ");
  const sources = [...new Set(job.sources.map((s) => s.source))];
  const draft = job.draft;

  return (
    <article
      aria-labelledby={`${id}-title`}
      className={cn("card space-y-3 p-4 sm:p-5", flash && "row-flash", job.status === "closed" && "opacity-70 hover:opacity-100")}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("rounded-md border px-2 py-0.5 text-xs font-medium", verdict?.tone ?? "border-line bg-surface-2 text-muted")}>
          {verdict?.label ?? "Not judged yet"}
        </span>
        {deadline && (
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs",
              deadline.soon ? "border border-warn-line bg-warn-bg text-warn-ink" : "bg-surface-2 text-ink/85",
            )}
          >
            <CalendarClock size={12} aria-hidden="true" />
            {deadline.text}
          </span>
        )}
        {sources.map((s) => (
          <span key={s} className="rounded-md bg-surface-2 px-2 py-0.5 text-xs text-ink/85">
            {SOURCES[s]}
          </span>
        ))}
        <label className="ml-auto inline-flex items-center gap-1.5 text-xs text-muted">
          Status
          <select
            value={job.status}
            onChange={(e) => onMark(job, e.target.value as JobStatus)}
            className="rounded-full border border-line-strong bg-surface px-2.5 py-1 text-sm text-ink hover:border-accent/40"
          >
            {JOB_STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUSES[s]}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div>
        <h3 id={`${id}-title`} className="break-words font-display text-xl leading-snug text-ink">
          {job.role}
          {job.company && <span className="text-muted"> at {job.company}</span>}
        </h3>
        {facts && <p className="mt-0.5 break-words text-sm text-muted">{facts}</p>}
      </div>

      {job.why && <p className="break-words text-sm leading-relaxed text-ink/90">{job.why}</p>}

      {job.suggested && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-warn-line bg-warn-bg px-3 py-2 text-sm text-warn-ink" role="note">
          <span className="min-w-0 flex-1 break-words">Looks applied: {job.suggested.why}</span>
          <ActionButton icon={Check} label="Yes, applied" tone="ok" name={`Yes, applied: ${job.role}`} onClick={() => onMark(job, "applied")} />
          <ActionButton icon={X} label="Not yet" tone="neutral" name={`Not yet: ${job.role}`} onClick={() => onMark(job, "not_applied")} />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {draft && draft.status && (
          <ActionButton
            icon={PenLine}
            label={draft.status === "draft" ? "Open draft" : `Draft ${draft.status}`}
            tone="accent"
            name={`Open draft: ${job.role}`}
            onClick={() => onDraft?.(draft.id)}
          />
        )}
        {draft && !draft.status && <span className="text-xs text-muted">Its first step is drafted on the next run.</span>}
        {job.errand && <ActionButton icon={Route} label="Start errand" tone="accent" name={`Start errand: ${job.errand}`} onClick={() => onErrand(job.errand)} />}
        {job.reply_link && job.step?.kind === "reply" && <OutLink href={job.reply_link}>{where(job.reply_link)}</OutLink>}
        {job.link && <OutLink href={job.link}>Open link</OutLink>}
        <button
          type="button"
          aria-expanded={open}
          aria-controls={`${id}-details`}
          onClick={() => setOpen((o) => !o)}
          className="ml-auto inline-flex items-center gap-1 rounded-full px-2 py-1 text-[0.8125rem] text-muted hover:text-ink"
        >
          {open ? "Fewer details" : "Details"}
          <ChevronDown size={14} aria-hidden="true" className={cn("transition-transform", open && "rotate-180")} />
        </button>
      </div>

      <dl id={`${id}-details`} hidden={!open} className="space-y-2.5 border-t border-line pt-3">
        <Fact label="The way in">
          {job.route ? (
            <>
              {ROUTES[job.route.kind] ?? job.route.kind}
              {job.route.why && <span className="text-muted">. {job.route.why}</span>}
            </>
          ) : (
            <span className="text-muted">Not judged yet.</span>
          )}
        </Fact>
        <Fact label="CV">
          {job.cv ? (
            <span className="inline-flex flex-wrap items-baseline gap-x-1.5">
              <FileText size={13} aria-hidden="true" className="self-center" />
              <span>
                {job.cv.name} <span className="text-muted">({job.cv.kind})</span>
              </span>
              {job.cv.why && <span className="text-muted">: {job.cv.why}</span>}
            </span>
          ) : (
            <span className="text-muted">None chosen.</span>
          )}
        </Fact>
        <Fact label="Whom to contact">
          {job.people.length > 0 ? (
            <ul className="space-y-1">
              {job.people.map((p) => (
                <li key={p.name} className="flex items-start gap-1.5">
                  <UserRound size={13} aria-hidden="true" className="mt-1 flex-shrink-0" />
                  <span>
                    {p.name}
                    {p.how && <span className="text-muted">, {p.how}</span>}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <span className="text-muted">No one in your records.</span>
          )}
        </Fact>
        {job.step && (
          <Fact label="First step">
            <span className="inline-flex items-center gap-1.5">
              <MessageSquareReply size={13} aria-hidden="true" />
              {stepLabel(job.step)}
            </span>
          </Fact>
        )}
        {job.sources.length > 0 && (
          <Fact label="Where it came from">
            <ul className="space-y-1 text-xs text-muted">
              {job.sources.map((s) =>
                s.id && onMemory ? (
                  <li key={`${s.id}${s.ts}`}>
                    <button type="button" onClick={() => onMemory(s.label, s.id)} className="inline-flex items-start gap-1 text-left hover:text-ink">
                      <span>{s.label}</span>
                      <Search size={11} aria-hidden="true" className="mt-0.5 flex-shrink-0" />
                      <span className="sr-only"> (open it in Memory)</span>
                    </button>
                  </li>
                ) : (
                  <li key={`${s.label}${s.ts}`}>{s.label}</li>
                ),
              )}
            </ul>
          </Fact>
        )}
        {job.status_at && (
          <Fact label="Status">
            {STATUSES[job.status]} since <span className="num">{timeAgo(job.status_at, now)}</span>
          </Fact>
        )}
      </dl>
    </article>
  );
}

interface JobsProps {
  /** Open a job's first step in Drafts. */
  onDraft?: (id: string) => void;
  /** Go to Errands once a job's errand has started. */
  onErrands?: () => void;
  /** Open where a job came from in Memory. */
  onMemory?: (query: string, id?: string) => void;
}

/**
 * Every job lead in one place, apply first: what and where, a verdict and why, the way in, the CV
 * that fits, whom to contact and the first step drafted. The status is the user's; applied is
 * suggested from their mail for them to confirm.
 */
export function Jobs({ onDraft, onErrands, onMemory }: JobsProps) {
  const { data, error, flashId, mark, clearError } = useJobs();
  const notify = useToast();
  const [status, setStatus] = useState<StatusFilter>("open");
  const [source, setSource] = useState<JobSource | "all">("all");
  const [errandError, setErrandError] = useState<string | null>(null);

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load jobs: ${error}`} /> : <ProseSkeleton label="Loading jobs" />;
  }
  if (!data.vault.exists) return <NoVault path={data.vault.path} />;
  if (!data.generated) {
    return (
      <EmptyState icon={BriefcaseBusiness} title="No job leads yet" command="proxenos clone jobs">
        Proxenos goes through the job leads that reached you (LinkedIn&apos;s alerts and messages, Work at a Startup&apos;s founders,
        recruiters&apos; emails, job boards, lists and the posts you share to Ask) and says for each whether to apply, how, with which CV
        and through whom, with the first step drafted. The night job runs it. Press Make it now to run it right away.
      </EmptyState>
    );
  }

  const startErrand = (goal: string) => {
    setErrandError(null);
    errandFromGoal(goal).then(
      () => {
        notify("Errand started", "ok");
        onErrands?.();
      },
      (e: unknown) => setErrandError(e instanceof Error ? e.message : String(e)),
    );
  };

  const shownSources = JOB_SOURCES.filter((s) => data.jobs.some((j) => j.sources.some((r) => r.source === s)));
  const shown = data.jobs.filter(
    (j) =>
      (status === "all" || (status === "open" ? j.status === "new" || j.status === "interested" : j.status === status)) &&
      (source === "all" || j.sources.some((s) => s.source === source)),
  );
  const toApply = shown.filter((j) => j.verdict === "apply").length;
  const statusCount = (s: StatusFilter) =>
    data.jobs.filter((j) => (s === "all" ? true : s === "open" ? j.status === "new" || j.status === "interested" : j.status === s)).length;

  return (
    <div className="pb-24 md:pb-20">
      {(error || errandError) && (
        <ErrorBanner
          message={errandError ?? error ?? ""}
          onDismiss={() => {
            setErrandError(null);
            clearError();
          }}
        />
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-4 py-3 text-sm text-muted sm:px-6">
        <label className="inline-flex items-center gap-2">
          <span>Status</span>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as StatusFilter)}
            className="rounded-full border border-line-strong bg-surface px-3 py-1 text-sm text-ink hover:border-accent/40"
          >
            <option value="open">Open ({statusCount("open")})</option>
            <option value="all">All ({statusCount("all")})</option>
            {JOB_STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUSES[s]} ({statusCount(s)})
              </option>
            ))}
          </select>
        </label>
        <label className="inline-flex items-center gap-2">
          <span>From</span>
          <select
            value={source}
            onChange={(e) => setSource(e.target.value as JobSource | "all")}
            className="rounded-full border border-line-strong bg-surface px-3 py-1 text-sm text-ink hover:border-accent/40"
          >
            <option value="all">Everywhere</option>
            {shownSources.map((s) => (
              <option key={s} value={s}>
                {SOURCES[s]}
              </option>
            ))}
          </select>
        </label>
        <span className="sm:ml-auto" aria-live="polite">
          <span className="num">{shown.length}</span> {shown.length === 1 ? "job" : "jobs"}, <span className="num">{toApply}</span> to apply for
          {" · "}
          <span title={formatDateTime(data.generated)}>
            gone through <span className="num">{timeAgo(data.generated, data.now)}</span>
          </span>
        </span>
      </div>

      <section aria-label="Jobs" className="space-y-4 p-4 sm:p-6">
        {data.cvs.length > 0 && (
          <p className="text-xs text-muted">
            Your CVs: {data.cvs.map((c) => `${c.name} (${c.kind})`).join(", ")}.
          </p>
        )}
        {shown.length > 0 ? (
          shown.map((job) => (
            <JobRow
              key={job.id}
              job={job}
              now={data.now}
              flash={flashId === job.id}
              onMark={mark}
              onDraft={onDraft}
              onErrand={startErrand}
              onMemory={onMemory}
            />
          ))
        ) : (
          <p className="text-sm text-muted">No jobs match these filters.</p>
        )}
        <p className="text-xs text-muted">
          Each status you set is appended to <code className="num">clones/jobs/status.jsonl</code> in the vault. Nothing is sent or applied
          for: drafts wait in Drafts. <Command>proxenos clone jobs</Command> goes through new leads now.
        </p>
      </section>
    </div>
  );
}
