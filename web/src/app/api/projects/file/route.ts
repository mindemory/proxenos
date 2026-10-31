import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { readMade } from "@/lib/projects";

export const dynamic = "force-dynamic";

/**
 * GET /api/projects/file?step=<project>/<when>&name=<file>: a figure or table a step made, from
 * the vault. Images are served as themselves, anything else as plain text or a PDF, and nothing
 * in one may run: no scripts, no requests, even an SVG opened on its own.
 */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  const url = new URL(req.url);
  const made = await readMade(url.searchParams.get("step") ?? "", url.searchParams.get("name") ?? "");
  if (!made) return Response.json({ error: "no such file" }, { status: 404 });
  return new Response(new Uint8Array(made.data), {
    headers: {
      ...NO_STORE,
      "Content-Type": made.type,
      "Content-Security-Policy": "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
