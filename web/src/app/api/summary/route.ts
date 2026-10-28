import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { getSummary } from "@/lib/summary";

export const dynamic = "force-dynamic";

/**
 * GET /api/summary: the landing page's counts (memories indexed, people, drafts awaiting
 * review, sources, last sync) and the network's shape as positions only, with no names.
 */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getSummary(), { headers: NO_STORE });
}
