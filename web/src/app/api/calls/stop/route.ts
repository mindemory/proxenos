import { CALL_ID, stopCall } from "@/lib/calls";
import { NO_STORE, readLocalJson } from "@/lib/guard";

export const dynamic = "force-dynamic";

/** POST /api/calls/stop {"id"} hangs up the call going from that sheet. */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { id } = parsed.body;
  if (typeof id !== "string" || !CALL_ID.test(id)) {
    return Response.json({ error: "id must be a call sheet's name" }, { status: 400 });
  }
  const result = await stopCall(id);
  return result.ok
    ? Response.json({ message: result.message }, { headers: NO_STORE })
    : Response.json({ error: result.error }, { status: result.status });
}
