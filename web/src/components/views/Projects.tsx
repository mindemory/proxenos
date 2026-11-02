"use client";

import { useEffect, useState } from "react";
import { ListPlus, MessagesSquare, Play, ScrollText, X } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { Fold } from "@/components/ask/parts";
import { ErrorBanner, NoVault } from "@/components/EmptyState";
import { Markdown } from "@/components/Markdown";
import { ManuscriptPanel } from "@/components/projects/Manuscript";
import { StepCard } from "@/components/projects/StepCard";
import { Bone } from "@/components/Skeleton";
import { timeAgo } from "@/lib/format";
import { useProjects } from "@/lib/projectsClient";
import { STEP_MAX_TEXT, type ManuscriptEdit, type ProjectsResponse, type StepAsk, type ThinkStart, type WorkProject } from "@/lib/types";

// What was being written in each project's queue box when the view was left.
const kept = new Map<string, string>();

interface SectionProps {
  project: WorkProject;
  data: ProjectsResponse;
  /** A step is being taken, on this project or another. */
  stepping: boolean;
  /** An Accept, Discard or queue change is going. */
  deciding: boolean;
  onTake: () => void;
  onQueue: (text: string) => Promise<boolean>;
  onUnqueue: (id: string) => void;
  onAccept: (step: string) => void;
  onDiscard: (step: string) => void;
  /** Ask for a step that says more than its words: queue it, or take it now. */
  onAsk: (text: string, now: boolean, ask: StepAsk) => Promise<boolean>;
  onSaveEdit: (edit: ManuscriptEdit) => Promise<boolean>;
  /** Think the project through with Proxenos, in a new thread that starts from it. */
  onThink?: () => void;
}

// Which projects' manuscripts were open when the view was left.
const reading = new Set<string>();

/** One project: where it stands, its manuscript, the steps asked for, and the steps taken, newest first. */
function ProjectSection({
  project,
  data,
  stepping,
  deciding,
  onTake,
  onQueue,
  onUnqueue,
  onAccept,
  onDiscard,
  onAsk,
  onSaveEdit,
  onThink,
}: SectionProps) {
  const [text, setText] = useState(kept.get(project.id) ?? "");
  const [queueing, setQueueing] = useState(false);
  const [paper, setPaper] = useState(reading.has(project.id));
  const showPaper = (open: boolean) => {
    setPaper(open);
    if (open) reading.add(project.id);
    else reading.delete(project.id);
  };
  // A step or an edit that comes, goes or is decided changes the manuscript's versions.
  const again = project.steps.map((s) => `${s.id}:${s.status}`).join(",");
  const mine = data.job?.state === "running" && data.job.project === project.id;
  const starting = mine && !project.steps.some((s) => s.status === "working");
  const waitingOnYou = project.steps.filter((s) => s.status === "ready").length;
  const canQueue = text.trim() !== "" && text.length <= STEP_MAX_TEXT && !queueing && !deciding;

  const write = (value: string) => {
    setText(value);
    kept.set(project.id, value);
  };
  const submit = async () => {
    if (!canQueue) return;
    setQueueing(true);
    if (await onQueue(text.trim())) write("");
    setQueueing(false);
  };

  return (
    <section id={`project-${project.id}`} aria-label={project.name} className="scroll-mt-4 space-y-4">
      <div className="space-y-1.5">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <h2 className="title-2 text-xl">{project.name}</h2>
          {project.paused && <span className="text-xs text-muted">paused</span>}
          {waitingOnYou > 0 && (
            <span className="text-xs text-warn-ink">
              {waitingOnYou} {waitingOnYou === 1 ? "step" : "steps"} waiting on you
            </span>
          )}
        </div>
        {project.about && <p className="text-sm leading-relaxed text-muted">{project.about}</p>}
        <p className="break-words text-xs text-muted">
          {project.repo ? (
            <>
              Code: <span className="font-mono text-ink/90">{project.repo}</span>
              {project.data.length > 0 && (
                <>
                  {" "}
                  · Data, read only: <span className="font-mono text-ink/90">{project.data.join(", ")}</span>
                </>
              )}
            </>
          ) : (
            <>
              No code folder yet, so no steps are taken on it: add its repository as &quot;repo&quot; in clones/projects/projects.json.
            </>
          )}
        </p>
      </div>

      {project.status && (
        <Fold label={`Where it stands${project.statusDate ? `, ${project.statusDate}` : ""}`} start>
          <Markdown source={project.status} compact />
        </Fold>
      )}

      {onThink && (
        <div>
          <ActionButton icon={MessagesSquare} label="Think it through" tone="neutral" onClick={onThink} />
        </div>
      )}

      {project.repo &&
        (paper ? (
          <ManuscriptPanel
            project={project.id}
            again={again}
            stepping={stepping}
            deciding={deciding}
            onAsk={onAsk}
            onSave={onSaveEdit}
            onClose={() => showPaper(false)}
          />
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <ActionButton icon={ScrollText} label="Manuscript" tone="accent" onClick={() => showPaper(true)} />
            <span className="text-xs text-muted">The paper&apos;s old and new versions, with the changes between them.</span>
          </div>
        ))}

      {project.repo && (
        <div className="card space-y-3 p-3 sm:p-4">
          <textarea
            value={text}
            onChange={(e) => write(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void submit();
            }}
            rows={2}
            aria-label={`A step for ${project.name}`}
            placeholder="A step for it to take, in your words: “Redo figure 3 with medians, not means.” Or leave it to pick the next one."
            className="w-full resize-none bg-transparent text-[15px] leading-relaxed text-ink placeholder:text-faint focus:outline-none"
          />
          {project.queue.length > 0 && (
            <ol className="space-y-1.5 border-l-2 border-line-strong pl-3">
              {project.queue.map((q, i) => (
                <li key={q.id} className="flex items-start justify-between gap-2 text-sm">
                  <span className="min-w-0 break-words text-ink/90">
                    <span className="num text-faint">{i + 1}.</span> {q.text}
                    {q.base && (
                      <span className="text-xs text-muted">
                        {" "}
                        · from <span className="font-mono">{q.base}</span>
                      </span>
                    )}
                  </span>
                  <button
                    onClick={() => onUnqueue(q.id)}
                    disabled={deciding}
                    aria-label="Take it off the queue"
                    className="flex-shrink-0 rounded p-0.5 text-faint transition-colors hover:text-bad-ink disabled:opacity-50"
                  >
                    <X size={14} />
                  </button>
                </li>
              ))}
            </ol>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-muted">
              {mine
                ? "Taking a step now. It can take half an hour."
                : stepping
                  ? "A step is being taken on another project: one at a time."
                  : project.queue.length
                    ? "The next step takes the first one queued."
                    : "Each night it takes one step, once the last is accepted or discarded."}
            </p>
            <div className="flex flex-wrap gap-2">
              <ActionButton
                icon={ListPlus}
                label={queueing ? "Queueing…" : "Queue it"}
                tone="neutral"
                disabled={!canQueue}
                onClick={() => void submit()}
              />
              <ActionButton
                icon={Play}
                label={mine ? "Working…" : "Do a step now"}
                tone="accent"
                disabled={stepping || project.paused}
                onClick={onTake}
              />
            </div>
          </div>
        </div>
      )}

      {starting && (
        <section aria-live="polite" className="card space-y-1 p-4 sm:p-5">
          <p className="smallcaps text-accent">Working on it</p>
          <p className="text-sm text-muted">
            Making a worktree for the step{data.job && ` · ${timeAgo(data.job.started, data.now)}`}.
          </p>
        </section>
      )}

      {project.steps.map((s) => (
        <StepCard
          key={`${s.id}-${s.updated}`}
          step={s}
          now={data.now}
          busy={deciding}
          stepping={stepping}
          onAccept={() => onAccept(s.id)}
          onDiscard={() => onDiscard(s.id)}
          onRevise={(text, now) => onAsk(text, now, { base: s.branch })}
        />
      ))}
    </section>
  );
}

/**
 * The user's long-running projects, each a step at a time: the twin does the next piece of the
 * work on a branch of the project's own code and comes back with what it did and what it shows,
 * for the user to accept, which merges it, or discard.
 */
interface ProjectsProps {
  onThink?: (start: ThinkStart) => void;
  /** A project to open on, by id, as Home's project tiles ask. */
  focus?: string | null;
  onFocused?: () => void;
}

export function Projects({ onThink, focus, onFocused }: ProjectsProps = {}) {
  const { data, error, clearError, waiting, take, takeAsked, accept, discard, queue, unqueue, saveEdit } = useProjects();
  const [focusId] = useState(focus ?? null);

  useEffect(() => {
    if (focus) onFocused?.();
  }, [focus, onFocused]);

  const found = data?.projects.some((p) => p.id === focusId) ?? false;
  useEffect(() => {
    if (!focusId || !found) return;
    // After the projects have rendered.
    const timer = window.setTimeout(
      () => document.getElementById(`project-${focusId}`)?.scrollIntoView({ behavior: "smooth", block: "start" }),
      60,
    );
    return () => window.clearTimeout(timer);
  }, [focusId, found]);

  if (data && !data.vault.exists) return <NoVault path={data.vault.path} />;

  const stepping = data?.job?.state === "running" || waiting.some((w) => w.kind === "step");
  const deciding = data?.deciding?.state === "running" || waiting.some((w) => w.kind === "decide");

  return (
    <div className="space-y-10 p-4 pb-24 sm:p-6 md:pb-20">
      {error && <ErrorBanner message={error} onDismiss={data ? clearError : undefined} />}

      {data === null ? (
        error ? null : (
          <div className="card space-y-3 p-5" aria-hidden="true">
            <Bone className="h-4 w-1/4" />
            <Bone className="h-4 w-full" />
            <Bone className="h-4 w-4/5" />
          </div>
        )
      ) : data.projects.length === 0 ? (
        <p className="max-w-2xl text-sm leading-relaxed text-muted">
          List your long-running projects in clones/projects/projects.json: a paper, an analysis, a thesis. Each night Proxenos writes
          where each one stands from your messages, mail and notes. Give one its code&apos;s folder (&quot;repo&quot;, a git repository)
          and its data folders, and it also does the next step of the work on a branch of its own: runs the analysis, fixes the
          script, makes the figure, drafts the section. It comes back here with what it did and what it shows, and you accept it,
          which merges it into your checkout, or discard it. Nothing is pushed, and no one is contacted.
        </p>
      ) : (
        data.projects.map((p) => (
          <ProjectSection
            key={p.id}
            project={p}
            data={data}
            stepping={stepping}
            deciding={deciding}
            onTake={() => void take(p.id)}
            onQueue={(text) => queue(p.id, text)}
            onUnqueue={(id) => void unqueue(p.id, id)}
            onAccept={(id) => void accept(id)}
            onDiscard={(id) => void discard(id)}
            onAsk={(text, now, ask) => (now ? takeAsked(p.id, text, ask) : queue(p.id, text, ask))}
            onSaveEdit={(edit) => saveEdit(p.id, edit)}
            onThink={
              onThink &&
              (() =>
                onThink({
                  kind: "project",
                  id: p.id,
                  label: `Project: ${p.name}`,
                  text: `Help me think through where ${p.name} stands and what to do next.`,
                }))
            }
          />
        ))
      )}
    </div>
  );
}
