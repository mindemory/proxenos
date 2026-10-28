import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { getHome } from "@/lib/vault";

export const dynamic = "force-dynamic";

/** GET /api/home?since=<ISO>: the opening brief, with "new" meaning newer than `since`. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  const since = new URL(req.url).searchParams.get("since");
  const valid = since && since.length <= 40 && !Number.isNaN(Date.parse(since)) ? since : null;
  return Response.json(await getHome(valid), { headers: NO_STORE });
}
