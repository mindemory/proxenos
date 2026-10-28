import { isLineSafeId, NO_STORE, readLocalJson } from "@/lib/guard";
import { TASK_ACTIONS, type TaskAction } from "@/lib/types";
import { appendTaskFeedback, VaultMissingError } from "@/lib/vault";

export const dynamic = "force-dynamic";

/** POST /api/tasks/feedback {"task_id", "action"} appends one line to clones/tasks/feedback.jsonl. */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { task_id: taskId, action } = parsed.body;
  if (!isLineSafeId(taskId)) {
    return Response.json({ error: "invalid task_id" }, { status: 400 });
  }
  if (typeof action !== "string" || !TASK_ACTIONS.includes(action as TaskAction)) {
    return Response.json({ error: `action must be one of ${TASK_ACTIONS.join(", ")}` }, { status: 400 });
  }

  try {
    const entry = await appendTaskFeedback(taskId, action as TaskAction);
    return Response.json({ ok: true, entry }, { headers: NO_STORE });
  } catch (e) {
    if (e instanceof VaultMissingError) {
      return Response.json({ error: `vault not found at ${e.message}` }, { status: 503 });
    }
    return Response.json({ error: "could not write feedback" }, { status: 500 });
  }
}
