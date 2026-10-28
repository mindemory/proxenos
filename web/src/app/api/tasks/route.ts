import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { getTasks } from "@/lib/vault";

export const dynamic = "force-dynamic";

/** GET /api/tasks: clones/tasks/tasks.json with the latest feedback per task. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getTasks(), { headers: NO_STORE });
}
