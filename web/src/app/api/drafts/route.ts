import { draftsView } from "@/lib/draftsView";
import { NO_STORE, rejectNonLocal } from "@/lib/guard";

export const dynamic = "force-dynamic";

/** GET /api/drafts: the drafts with what each can open and how reviews have gone (lib/draftsView). Nothing is sent. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await draftsView(), { headers: NO_STORE });
}
