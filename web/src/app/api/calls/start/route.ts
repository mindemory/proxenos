import { CALL_ID, startCall } from "@/lib/calls";
import { NO_STORE, readLocalJson } from "@/lib/guard";

export const dynamic = "force-dynamic";

/** POST /api/calls/start {"id"} places the call on that sheet: the one way the page dials anyone. */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { id } = parsed.body;
  if (typeof id !== "string" || !CALL_ID.test(id)) {
    return Response.json({ error: "id must be a call sheet's name" }, { status: 400 });
  }
  const result = await startCall(id);
  return result.ok
    ? Response.json({ message: result.message }, { status: 202, headers: NO_STORE })
    : Response.json({ error: result.error }, { status: result.status });
}
