import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { getWatch } from "@/lib/vault";

export const dynamic = "force-dynamic";

/** GET /api/watch (the newest week) or /api/watch?date=YYYY-MM-DD, plus every available date. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  const date = new URL(req.url).searchParams.get("date");
  return Response.json(await getWatch(date && /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : null), {
    headers: NO_STORE,
  });
}
