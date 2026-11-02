import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { getRhythms } from "@/lib/rhythms";

export const dynamic = "force-dynamic";

/** GET /api/rhythms: every week from the first with a record to this one, and what stands out. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getRhythms(), { headers: NO_STORE });
}
