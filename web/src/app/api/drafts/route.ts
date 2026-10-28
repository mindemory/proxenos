import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { getDrafts } from "@/lib/vault";

export const dynamic = "force-dynamic";

/** GET /api/drafts: every file in clones/drafts, newest first. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getDrafts(), { headers: NO_STORE });
}
