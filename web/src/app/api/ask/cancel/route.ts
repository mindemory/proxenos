import { stopJob } from "@/lib/connect";
import { NO_STORE, readLocalJson } from "@/lib/guard";

export const dynamic = "force-dynamic";

/** POST /api/ask/cancel {} stops the ask that's running. */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  return Response.json({ stopped: stopJob("ask") }, { headers: NO_STORE });
}
