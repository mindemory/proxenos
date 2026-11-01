import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { getPrivacy } from "@/lib/privacy";

export const dynamic = "force-dynamic";

/**
 * GET /api/privacy: what stays on this computer, what went to a model in the last 30 days, and
 * what's read from elsewhere. Paths, names, addresses and counts; never a message, prompt or key.
 */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getPrivacy(), { headers: NO_STORE });
}
