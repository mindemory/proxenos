import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { MAX_ID_CHARS, MemoryUnavailableError, memoryContext } from "@/lib/memory";

export const dynamic = "force-dynamic";

/** GET /api/memory/context?id=: a record and the ones around it in the same chat, channel or thread. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  const id = new URL(req.url).searchParams.get("id") ?? "";
  if (!id || id.length > MAX_ID_CHARS) {
    return Response.json({ error: "bad id" }, { status: 400, headers: NO_STORE });
  }
  try {
    const found = memoryContext(id);
    if (!found) return Response.json({ error: "not found" }, { status: 404, headers: NO_STORE });
    return Response.json(found, { headers: NO_STORE });
  } catch (e) {
    const unavailable = e instanceof MemoryUnavailableError;
    console.error(`memory context failed: ${e instanceof Error ? e.name : "unknown"}`);
    return Response.json(
      { error: unavailable ? e.message : "memory context failed" },
      { status: unavailable ? 503 : 500, headers: NO_STORE },
    );
  }
}
