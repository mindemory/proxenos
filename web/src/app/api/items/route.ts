import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { getFeed, getSaved } from "@/lib/vault";

export const dynamic = "force-dynamic";

/** GET /api/items?batches=3 (feed) or /api/items?view=saved */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;

  const params = new URL(req.url).searchParams;
  if (params.get("view") === "saved") {
    return Response.json(await getSaved(), { headers: NO_STORE });
  }
  const n = Number.parseInt(params.get("batches") ?? "", 10);
  const batches = Number.isFinite(n) ? Math.min(20, Math.max(1, n)) : 3;
  return Response.json(await getFeed(batches), { headers: NO_STORE });
}
