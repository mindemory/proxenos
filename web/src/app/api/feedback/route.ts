import { isLineSafeId, NO_STORE, readLocalJson } from "@/lib/guard";
import { ACTIONS, type Action } from "@/lib/types";
import { appendFeedback, VaultMissingError } from "@/lib/vault";

export const dynamic = "force-dynamic";

/** POST /api/feedback {"item_id", "action"} appends one line to tracker/feedback.jsonl. */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { item_id: itemId, action } = parsed.body;
  if (!isLineSafeId(itemId)) {
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
