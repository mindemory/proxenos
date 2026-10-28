"use client";

import { useState } from "react";
import { ChevronRight, ListTodo } from "lucide-react";

import { EmptyState, ErrorBanner, LoadingRows, NoVault } from "@/components/EmptyState";
import { TaskRow } from "@/components/tasks/TaskRow";
import { useTasks } from "@/lib/client";
import { formatDateTime, timeAgo } from "@/lib/format";
import { groupTasks } from "@/lib/tasks";
import { TASK_ACTIONS, type TaskView } from "@/lib/types";
import { cn } from "@/lib/utils";

function SectionHeader({ title, count, hint }: { title: string; count: number; hint?: string }) {
  return (
    <div className="px-4 sm:px-6 py-2 border-b border-line bg-surface/60 flex justify-between gap-3">
      <span className="eyebrow">
        {title}
        {hint && <span className="normal-case tracking-normal"> · {hint}</span>}
      </span>
      <span className="num text-xs text-muted">{count}</span>
    </div>
  );
}

export function Tasks({ onChange }: { onChange?: () => void }) {
  const { data, error, flashId, act, clearError } = useTasks(onChange);
  const [showDone, setShowDone] = useState(false);

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load tasks: ${error}`} /> : <LoadingRows />;
  }

  if (!data.vault.exists) return <NoVault path={data.vault.path} />;

  if (!data.exists) {
    return (
      <EmptyState icon={ListTodo} title="No task list yet" command="twin clone tasks">
        The tasks clone reads WhatsApp, Slack and email for things people asked you to do, and lists each one with who
        asked, when, and when it&apos;s due. Run it to build the list.
      </EmptyState>
    );
  }

  const g = groupTasks(data.tasks, data.now);
  const openCount = g.urgent.length + g.open.length;

  const list = (tasks: TaskView[]) => (
    <ul className="divide-y divide-line border-b border-line">
      {tasks.map((t) => (
        <TaskRow key={t.id} task={t} now={data.now} actions={TASK_ACTIONS} onAct={act} flash={flashId === t.id} />
      ))}
    </ul>
  );

  return (
    <div className="pb-24 md:pb-20">
      {error && <ErrorBanner message={error} onDismiss={clearError} />}

      <div className="px-4 sm:px-6 py-3 border-b border-line flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-sm text-muted">
        <span>
          <span className="num text-ink">{openCount}</span> open · <span className="num">{g.urgent.length}</span> overdue
          or due soon · <span className="num">{g.waiting.length}</span> waiting
        </span>
        {data.generated && (
          <span title={formatDateTime(data.generated)}>
            Generated <span className="num">{timeAgo(data.generated, data.now)}</span>
          </span>
        )}
      </div>

      {g.urgent.length > 0 && (
        <section>
          <SectionHeader title="Overdue and due soon" count={g.urgent.length} />
          {list(g.urgent)}
        </section>
      )}

      <section>
        <SectionHeader title="Open" hint="high priority first" count={g.open.length} />
        {g.open.length > 0 ? (
          list(g.open)
        ) : (
          <p className="px-4 sm:px-6 py-4 text-sm text-muted border-b border-line">
            {g.urgent.length ? "Nothing else open." : "Nothing open. New requests show up after the next run of twin clone tasks."}
          </p>
        )}
      </section>

      {g.waiting.length > 0 && (
        <section>
          <SectionHeader title="Waiting on others" count={g.waiting.length} />
          {list(g.waiting)}
        </section>
      )}

      {g.done.length > 0 && (
        <section>
          <button
            onClick={() => setShowDone((v) => !v)}
            aria-expanded={showDone}
            className={cn(
              "w-full px-4 sm:px-6 py-2 border-b border-line bg-surface/60 flex justify-between gap-3 text-left hover:bg-surface",
              flashId === "group:done" && "row-flash",
            )}
          >
            <span className="eyebrow inline-flex items-center gap-1">
              <ChevronRight size={12} className={cn("transition-transform", showDone && "rotate-90")} />
              Done recently
            </span>
            <span className="num text-xs text-muted">{g.done.length}</span>
          </button>
          {showDone && (
            <ul className="divide-y divide-line border-b border-line">
              {g.done.map((t) => (
                <TaskRow key={t.id} task={t} now={data.now} showEvidence={false} />
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
