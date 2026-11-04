import { CALL_ID, startCall } from "@/lib/calls";
import { NO_STORE, readLocalJson } from "@/lib/guard";

export const dynamic = "force-dynamic";

/**
 * POST /api/calls/start {"id", "anyway"?} places the call on that sheet: the one way the page dials
 * anyone. A number the vault has from just one message to the reader is refused, with why, unless
 * "anyway" is true, which the page sends only from "Call anyway" once it has shown why.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { id, anyway } = parsed.body;
  if (typeof id !== "string" || !CALL_ID.test(id)) {
    return Response.json({ error: "id must be a call sheet's name" }, { status: 400 });
  }
  if (anyway !== undefined && typeof anyway !== "boolean") {
    return Response.json({ error: "anyway must be true or false" }, { status: 400 });
  }
  const result = await startCall(id, anyway === true);
  return result.ok
    ? Response.json({ message: result.message }, { status: 202, headers: NO_STORE })
    : Response.json({ error: result.error }, { status: result.status });
}
