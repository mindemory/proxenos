import { isLineSafeId, NO_STORE, readLocalJson } from "@/lib/guard";
import { CHOICE_ACTIONS, type ChoiceAction } from "@/lib/types";
import { appendChoiceFeedback, VaultMissingError } from "@/lib/vault";

export const dynamic = "force-dynamic";

/** POST /api/choices/feedback {"item_id", "action"} appends one line to clones/choices/feedback.jsonl. */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { item_id: itemId, action } = parsed.body;
  if (!isLineSafeId(itemId)) {
    return Response.json({ error: "invalid item_id" }, { status: 400 });
  }
  if (typeof action !== "string" || !CHOICE_ACTIONS.includes(action as ChoiceAction)) {
    return Response.json({ error: `action must be one of ${CHOICE_ACTIONS.join(", ")}` }, { status: 400 });
  }

  try {
    const entry = await appendChoiceFeedback(itemId, action as ChoiceAction);
    return Response.json({ ok: true, entry }, { headers: NO_STORE });
  } catch (e) {
    if (e instanceof VaultMissingError) {
      return Response.json({ error: `vault not found at ${e.message}` }, { status: 503 });
    }
    return Response.json({ error: "could not write feedback" }, { status: 500 });
  }
}
