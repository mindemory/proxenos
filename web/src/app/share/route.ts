import { ASK_MAX_BODY, parseAsk, startAsk } from "@/lib/ask";
import { rejectNonLocal } from "@/lib/guard";
import { ASK_MAX_IMAGES } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * POST /share: what's shared to the installed app from the phone's share sheet (the manifest's
 * share_target): a title, text or link, and up to four screenshots. It's asked about as on the
 * Ask page, then the app opens there to follow the answer. Nothing is kept from the request but
 * the question the ask is given.
 */
export async function POST(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  if (Number(req.headers.get("content-length") ?? 0) > ASK_MAX_BODY) {
    return Response.json({ error: "too much to share at once" }, { status: 413 });
  }
  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return Response.json({ error: "expected a form" }, { status: 400 });
  }
  const text = ["title", "text", "url"]
    .map((key) => form.get(key))
    .filter((value): value is string => typeof value === "string" && value.trim() !== "")
    .join("\n");
  const files = form
    .getAll("images")
    .filter((f): f is File => typeof f !== "string")
    .slice(0, ASK_MAX_IMAGES);
  const images = await Promise.all(
    files.map(async (f) => ({ type: f.type, data: Buffer.from(await f.arrayBuffer()).toString("base64") })),
  );
  const question = parseAsk({ text, images });
  // Busy or not askable, the app still opens on Ask, which shows how things stand.
  if (!("error" in question)) await startAsk(question);
  return new Response(null, { status: 303, headers: { Location: "/app?view=ask" } });
}
