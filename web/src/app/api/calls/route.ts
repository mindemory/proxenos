import { getCalls } from "@/lib/calls";
import { NO_STORE, rejectNonLocal } from "@/lib/guard";

export const dynamic = "force-dynamic";

/** GET /api/calls: the call sheets, the call going from each, and the last few it made. Cheap enough to poll. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getCalls(), { headers: NO_STORE });
}
