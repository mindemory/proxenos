import { NO_STORE, readLocalJson } from "@/lib/guard";
import { DRAFT_ACTIONS, type DraftAction } from "@/lib/types";
import {
  applyDraftAction,
  DRAFT_ID,
  DraftFormatError,
  DraftNotFoundError,
  DraftTooLargeError,
  MAX_DRAFT_BYTES,
  VaultMissingError,
} from "@/lib/vault";

export const dynamic = "force-dynamic";

/**
 * POST /api/drafts/feedback {"draft_id", "action", "body"?}
 *
 * approve and discard set the draft's status in its file, edit replaces its
 * body (and needs "body"), and copy only logs that the text was copied. Every
 * action appends {draft_id, action, ts} to clones/drafts/feedback.jsonl.
 * Nothing is ever sent anywhere.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { draft_id: draftId, action, body } = parsed.body;
  if (typeof draftId !== "string" || !DRAFT_ID.test(draftId)) {
    return Response.json({ error: "invalid draft_id" }, { status: 400 });
  }
  if (typeof action !== "string" || !DRAFT_ACTIONS.includes(action as DraftAction)) {
    return Response.json({ error: `action must be one of ${DRAFT_ACTIONS.join(", ")}` }, { status: 400 });
  }
  // A character is at least a byte, so this only turns away what could never fit.
  if (action === "edit" && (typeof body !== "string" || body.length > MAX_DRAFT_BYTES)) {
    return Response.json({ error: "edit needs a body that fits in a draft file" }, { status: 400 });
  }

  try {
    const entry = await applyDraftAction(draftId, action as DraftAction, typeof body === "string" ? body : undefined);
    return Response.json({ ok: true, entry }, { headers: NO_STORE });
  } catch (e) {
    if (e instanceof VaultMissingError) {
      return Response.json({ error: `vault not found at ${e.message}` }, { status: 503 });
    }
    if (e instanceof DraftNotFoundError) {
      return Response.json({ error: "no such draft" }, { status: 404 });
    }
    if (e instanceof DraftFormatError) {
      return Response.json({ error: "this draft has no front matter to update" }, { status: 422 });
    }
    if (e instanceof DraftTooLargeError) {
      return Response.json({ error: "the draft would be too large to read back" }, { status: 413 });
    }
    return Response.json({ error: "could not save the draft" }, { status: 500 });
  }
}
