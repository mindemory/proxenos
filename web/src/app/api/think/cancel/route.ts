import { stopJob } from "@/lib/connect";
import { NO_STORE, readLocalJson } from "@/lib/guard";

export const dynamic = "force-dynamic";

/** POST /api/think/cancel {} stops the think that's running. */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  return Response.json({ stopped: stopJob("think") }, { headers: NO_STORE });
}
