import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { getTwin } from "@/lib/vault";

export const dynamic = "force-dynamic";

/** GET /api/twin: the self/*.md files, read-only. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getTwin(), { headers: NO_STORE });
}
