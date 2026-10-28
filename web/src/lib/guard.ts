// The app binds to 127.0.0.1, but a page on another site can still make the
// browser send requests here. Only answer requests addressed to a loopback
// host (blocks DNS rebinding), and refuse cross-origin callers.

const LOOPBACK = new Set(["127.0.0.1", "localhost", "[::1]"]);

export function rejectNonLocal(req: Request): Response | null {
  const host = req.headers.get("host") ?? "";
  const hostname = host.replace(/:\d+$/, "").toLowerCase();
  if (!LOOPBACK.has(hostname)) {
    return Response.json({ error: "forbidden" }, { status: 403 });
  }
  const origin = req.headers.get("origin");
  if (origin !== null) {
    let originHost = "";
    try {
      originHost = new URL(origin).host;
    } catch {
      // "null" or garbage: treated as a mismatch below.
    }
    if (originHost !== host) return Response.json({ error: "forbidden" }, { status: 403 });
  }
  return null;
}

export const NO_STORE = { "Cache-Control": "no-store" };

/**
 * Guard for a POST that writes to the vault: loopback host, same origin, and a
 * JSON body. A cross-site form can't send application/json without a
 * preflight, which this server never answers. Returns the parsed body, or the
 * response to send instead.
 */
export async function readLocalJson(req: Request): Promise<{ body: Record<string, unknown> } | { denied: Response }> {
  const denied = rejectNonLocal(req);
  if (denied) return { denied };
  if (!(req.headers.get("content-type") ?? "").startsWith("application/json")) {
    return { denied: Response.json({ error: "expected application/json" }, { status: 415 }) };
  }
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return { denied: Response.json({ error: "invalid JSON" }, { status: 400 }) };
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return { denied: Response.json({ error: "expected a JSON object" }, { status: 400 }) };
  }
  return { body: body as Record<string, unknown> };
}

/** An id that is safe to write as one JSON line. */
export function isLineSafeId(v: unknown): v is string {
  return typeof v === "string" && v.length > 0 && v.length <= 256 && !/[\r\n]/.test(v);
}
