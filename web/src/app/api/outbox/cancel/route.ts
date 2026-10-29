import { isLineSafeId, NO_STORE, readLocalJson } from "@/lib/guard";
import { appendOutboxCancel, VaultMissingError } from "@/lib/vault";

export const dynamic = "force-dynamic";

/**
 * POST /api/outbox/cancel {"draft_id"} stops a queued reply from going out: it appends
 * {draft_id, at} to clones/outbox/cancelled.jsonl, which the sync reads before it sends. The id
 * needn't be queued right now, since the queue may have moved on; a cancel for a draft that isn't
 * waiting changes nothing.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { draft_id: draftId } = parsed.body;
  if (!isLineSafeId(draftId)) return Response.json({ error: "invalid draft_id" }, { status: 400 });

  try {
    await appendOutboxCancel(draftId);
  } catch (e) {
    if (e instanceof VaultMissingError) {
      return Response.json({ error: `vault not found at ${e.message}` }, { status: 503 });
    }
    return Response.json({ error: "could not save the cancel" }, { status: 500 });
  }
  return Response.json({ ok: true }, { headers: NO_STORE });
}
