import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { getNetwork } from "@/lib/vault";

export const dynamic = "force-dynamic";

/** GET /api/network: people.json and ideas.json, with the latest feedback per idea. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getNetwork(), { headers: NO_STORE });
}
