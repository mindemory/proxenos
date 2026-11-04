"use client";

// The Jobs view's data and its one action: setting a job's status, or setting aside the
// suggestion that it was applied for. The change shows at once and is undone if it can't be saved.

import { useCallback } from "react";

import { useToast } from "@/components/Toasts";

import { useFlash, useJson } from "./client";
import type { Job, JobAction, JobsResponse, JobStatus } from "./types";
import { JSON_HEADERS } from "./headers";

const SAVED: Record<JobAction, string> = {
  new: "Marked new",
  interested: "Marked interested",
  applied: "Marked applied",
  interviewing: "Marked interviewing",
  closed: "Closed",
  not_applied: "Set aside: not applied yet",
};

async function sendJobStatus(jobId: string, action: JobAction): Promise<void> {
  const res = await fetch("/api/jobs", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ job_id: jobId, action }),
    keepalive: true,
  });
  if (!res.ok) throw new Error(`/api/jobs returned ${res.status}`);
}

export function useJobs() {
  const { data, error, setData, setError } = useJson<JobsResponse>("/api/jobs");
  const notify = useToast();
  const { flashId, flash } = useFlash();

  const mark = useCallback(
    (job: Job, action: JobAction) => {
      if (action === job.status) return;
      const set = (patch: Partial<Job>) =>
        setData((d) => (d ? { ...d, jobs: d.jobs.map((j) => (j.id === job.id ? { ...j, ...patch } : j)) } : d));
      const at = new Date().toISOString();
      const next: Partial<Job> =
        action === "not_applied"
          ? { suggested: null }
          : { status: action as JobStatus, status_at: at, suggested: action === "new" || action === "interested" ? job.suggested : null };
      flash(job.id);
      set(next);
      sendJobStatus(job.id, action).then(
        () => notify(SAVED[action], action === "closed" || action === "not_applied" ? "info" : "ok"),
        () => {
          set({ status: job.status, status_at: job.status_at, suggested: job.suggested });
          setError("Couldn't save that. Is the vault reachable? Nothing was written.");
        },
      );
    },
    [setData, setError, flash, notify],
  );

  return { data, error, flashId, mark, clearError: () => setError(null) };
}
