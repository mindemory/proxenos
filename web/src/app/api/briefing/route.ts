import { getBriefing } from "@/lib/briefing";
import { NO_STORE, rejectNonLocal } from "@/lib/guard";

export const dynamic = "force-dynamic";

/**
 * GET /api/briefing: what the Home briefing shows beside /api/home: today's agenda from the
 * recall clone, records per source per day over the last 30 days, and draft review rates.
 */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getBriefing(), { headers: NO_STORE });
}
