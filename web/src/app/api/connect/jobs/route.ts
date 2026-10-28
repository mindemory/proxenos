import { connectJobs } from "@/lib/connect";
import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { nowIso } from "@/lib/vault";

export const dynamic = "force-dynamic";

/** GET /api/connect/jobs: the sign-ins and reads, running or how they ended. Cheap enough to poll. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json({ now: nowIso(), jobs: connectJobs() }, { headers: NO_STORE });
}
