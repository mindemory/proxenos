import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { getStatus } from "@/lib/vault";

export const dynamic = "force-dynamic";

/** GET /api/status: last sync per raw source and tracker totals. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getStatus(), { headers: NO_STORE });
}
