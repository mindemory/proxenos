// Server side of the jobs the page follows by their last line: a model's download and "Make it
// now". Import only from route handlers. A job's message is its command's last line, with
// anything that looks like a token blanked (connect.ts lastLine).

import { type Job, latestJob } from "./connect";
import type { JobKind, RunJob } from "./types";

/** The latest job of this kind as the page follows it, or null before the first since the server started. */
export function runJob(kind: JobKind): RunJob | null {
  const job: Job | null = latestJob(kind);
  if (!job) return null;
  return { state: job.state, message: job.message, command: job.account, started: job.started, finished: job.finished };
}
