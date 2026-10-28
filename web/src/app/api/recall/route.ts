import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { getRecall } from "@/lib/memory";

export const dynamic = "force-dynamic";

/** GET /api/recall: today's triggers (events, tasks, feed, people) with the memories they bring up. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getRecall(), { headers: NO_STORE });
}
