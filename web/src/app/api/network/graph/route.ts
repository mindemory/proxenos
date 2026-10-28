import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { getGraphThumb } from "@/lib/vault";

export const dynamic = "force-dynamic";

/** GET /api/network/graph: the busiest connected people and their ties, for the home thumbnail. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getGraphThumb(), { headers: NO_STORE });
}
