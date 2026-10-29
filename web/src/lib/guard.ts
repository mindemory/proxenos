// The app binds to 127.0.0.1, but a page on another site can still make the
// browser send requests here. Only answer requests addressed to a loopback
// host (blocks DNS rebinding), and refuse cross-origin callers.
//
// The one other way in is the user's phone through Tailscale Serve (`proxenos phone`):
// their Mac's private address on their own tailnet, PROXENOS_REMOTE_HOST, which Serve
// forwards here saying which Tailscale login is asking. That address answers only the
// user's own login, PROXENOS_REMOTE_USER.

import { setting } from "./vault";

const LOOPBACK = new Set(["127.0.0.1", "localhost", "[::1]"]);

function fromTheUser(req: Request, hostname: string): boolean {
  if (LOOPBACK.has(hostname)) return true;
  const remote = setting("REMOTE_HOST")?.toLowerCase();
  const user = setting("REMOTE_USER")?.toLowerCase();
  const login = req.headers.get("tailscale-user-login")?.toLowerCase();
  return !!remote && !!user && hostname === remote && login === user;
}

export function rejectNonLocal(req: Request): Response | null {
  const host = req.headers.get("host") ?? "";
  const hostname = host.replace(/:\d+$/, "").toLowerCase();
  if (!fromTheUser(req, hostname)) {
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
export async function readLocalJson(
  req: Request,
  maxBytes?: number,
): Promise<{ body: Record<string, unknown> } | { denied: Response }> {
  const denied = rejectNonLocal(req);
  if (denied) return { denied };
  if (!(req.headers.get("content-type") ?? "").startsWith("application/json")) {
    return { denied: Response.json({ error: "expected application/json" }, { status: 415 }) };
  }
  let body: unknown;
  try {
    if (maxBytes === undefined) body = await req.json();
    else {
      // A route that takes a big body (screenshots) names how big, and nothing past it is read.
      const text = await readCapped(req, maxBytes);
      if (text === null) return { denied: Response.json({ error: "that is too large" }, { status: 413 }) };
      body = JSON.parse(text);
    }
  } catch {
    return { denied: Response.json({ error: "invalid JSON" }, { status: 400 }) };
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return { denied: Response.json({ error: "expected a JSON object" }, { status: 400 }) };
  }
  return { body: body as Record<string, unknown> };
}

/** The request's body as text, or null once it passes `maxBytes` (the rest is not read). */
async function readCapped(req: Request, maxBytes: number): Promise<string | null> {
  const declared = Number(req.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > maxBytes) return null;
  const reader = req.body?.getReader();
  if (!reader) return "";
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  return Buffer.concat(chunks).toString("utf8");
}

/** An id that is safe to write as one JSON line. */
export function isLineSafeId(v: unknown): v is string {
  return typeof v === "string" && v.length > 0 && v.length <= 256 && !/[\r\n]/.test(v);
}
