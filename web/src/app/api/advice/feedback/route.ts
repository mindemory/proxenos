import { isLineSafeId, NO_STORE, readLocalJson } from "@/lib/guard";
import { ADVICE_ACTIONS, type AdviceAction } from "@/lib/types";
import { appendAdviceFeedback, VaultMissingError } from "@/lib/vault";

export const dynamic = "force-dynamic";

/** POST /api/advice/feedback {"suggestion_id", "action"} appends one line to clones/advisor/feedback.jsonl. */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { suggestion_id: suggestionId, action } = parsed.body;
  if (!isLineSafeId(suggestionId)) {
    return Response.json({ error: "invalid suggestion_id" }, { status: 400 });
  }
  if (typeof action !== "string" || !ADVICE_ACTIONS.includes(action as AdviceAction)) {
    return Response.json({ error: `action must be one of ${ADVICE_ACTIONS.join(", ")}` }, { status: 400 });
  }

  try {
    const entry = await appendAdviceFeedback(suggestionId, action as AdviceAction);
    return Response.json({ ok: true, entry }, { headers: NO_STORE });
  } catch (e) {
    if (e instanceof VaultMissingError) {
      return Response.json({ error: `vault not found at ${e.message}` }, { status: 503 });
    }
    return Response.json({ error: "could not write feedback" }, { status: 500 });
  }
}
