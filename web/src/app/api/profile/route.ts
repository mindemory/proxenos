import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { getProfile } from "@/lib/vault";

export const dynamic = "force-dynamic";

/** GET /api/profile: the self/*.md files, read-only. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getProfile(), { headers: NO_STORE });
}
