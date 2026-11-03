import { NO_STORE, readLocalJson, rejectNonLocal } from "@/lib/guard";
import { appendJobStatus, getJobs, isJobAction, isJobId } from "@/lib/jobs";
import { JOB_ACTIONS } from "@/lib/types";
import { VaultMissingError } from "@/lib/vault";

export const dynamic = "force-dynamic";

/** GET /api/jobs: every job lead the jobs clone went through, apply first, with the user's status of each. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getJobs(), { headers: NO_STORE });
}

/** POST /api/jobs {"job_id", "action"} appends one line to clones/jobs/status.jsonl: a status, or not_applied. */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { job_id: jobId, action } = parsed.body;
  if (!isJobId(jobId)) return Response.json({ error: "invalid job_id" }, { status: 400 });
  if (!isJobAction(action)) {
    return Response.json({ error: `action must be one of ${JOB_ACTIONS.join(", ")}` }, { status: 400 });
  }
  try {
    const entry = await appendJobStatus(jobId, action);
    return Response.json({ ok: true, entry }, { headers: NO_STORE });
  } catch (e) {
    if (e instanceof VaultMissingError) {
      return Response.json({ error: `vault not found at ${e.message}` }, { status: 503 });
    }
    return Response.json({ error: "could not write the status" }, { status: 500 });
  }
}
