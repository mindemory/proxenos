import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { ACTIONS, type Action } from "@/lib/types";
import { appendFeedback, VaultMissingError } from "@/lib/vault";

export const dynamic = "force-dynamic";

/** POST /api/feedback {"item_id", "action"} appends one line to tracker/feedback.jsonl. */
export async function POST(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;

  // JSON only: a cross-site form can't send this content type without a preflight.
  if (!(req.headers.get("content-type") ?? "").startsWith("application/json")) {
    return Response.json({ error: "expected application/json" }, { status: 415 });
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "invalid JSON" }, { status: 400 });
  }
  const { item_id: itemId, action } = (body ?? {}) as Record<string, unknown>;
  if (typeof itemId !== "string" || itemId.length === 0 || itemId.length > 256 || /[\r\n]/.test(itemId)) {
    return Response.json({ error: "invalid item_id" }, { status: 400 });
  }
  if (typeof action !== "string" || !ACTIONS.includes(action as Action)) {
    return Response.json({ error: `action must be one of ${ACTIONS.join(", ")}` }, { status: 400 });
  }

  try {
    const entry = await appendFeedback(itemId, action as Action);
    return Response.json({ ok: true, entry }, { headers: NO_STORE });
  } catch (e) {
    if (e instanceof VaultMissingError) {
      return Response.json({ error: `vault not found at ${e.message}` }, { status: 503 });
    }
    return Response.json({ error: "could not write feedback" }, { status: 500 });
  }
}
