import { stopJob } from "@/lib/connect";
import { NO_STORE, readLocalJson } from "@/lib/guard";
import { CONNECT_JOB_KINDS, type ConnectJobKind } from "@/lib/types";

export const dynamic = "force-dynamic";

/** POST /api/connect/cancel {kind} stops a running sign-in or read. */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const kind = parsed.body.kind as ConnectJobKind;
  if (!CONNECT_JOB_KINDS.includes(kind)) return Response.json({ error: "unknown kind" }, { status: 400 });
  return Response.json({ stopped: stopJob(kind) }, { headers: NO_STORE });
}
