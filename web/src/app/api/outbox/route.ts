import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { getOutbox } from "@/lib/vault";

export const dynamic = "force-dynamic";

/**
 * GET /api/outbox: the rules for replies that go out on their own (the defaults, everything off,
 * until the page has saved any), what the last sync worked out (null before the first), the
 * drafts cancelled, and the 50 newest attempts to send, newest first. Nothing here sends.
 */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getOutbox(), { headers: NO_STORE });
}
