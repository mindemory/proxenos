import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { MemoryUnavailableError, parseSearch, searchMemory } from "@/lib/memory";

export const dynamic = "force-dynamic";

/**
 * GET /api/memory/search?q=&source=a,b&who=&since=YYYY-MM-DD&until=YYYY-MM-DD&limit=:
 * full-text search over everything in raw/, read-only. Typed text is quoted word by word before
 * it reaches the index, so it can't be anything but words.
 */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  const parsed = parseSearch(new URL(req.url).searchParams);
  if ("error" in parsed) return Response.json({ error: parsed.error }, { status: 400, headers: NO_STORE });
  try {
    return Response.json(searchMemory(parsed.params), { headers: NO_STORE });
  } catch (e) {
    const unavailable = e instanceof MemoryUnavailableError;
    // The message could echo what was typed, so only the kind of failure is logged.
    console.error(`memory search failed: ${e instanceof Error ? e.name : "unknown"}`);
    return Response.json(
      { error: unavailable ? e.message : "memory search failed" },
      { status: unavailable ? 503 : 500, headers: NO_STORE },
    );
  }
}
