import { getConnect } from "@/lib/connect";
import { NO_STORE, rejectNonLocal } from "@/lib/guard";

export const dynamic = "force-dynamic";

/** GET /api/connect: every source, whether it's connected, and the sign-ins and reads running. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getConnect(), { headers: NO_STORE });
}
