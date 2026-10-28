import { getCare } from "@/lib/care";
import { NO_STORE, rejectNonLocal } from "@/lib/guard";

export const dynamic = "force-dynamic";

/** GET /api/care: clones/care/care.json with the latest mark on each open item. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getCare(), { headers: NO_STORE });
}
