import { NO_STORE, readLocalJson } from "@/lib/guard";
import { deleteClip, MAX_CLIP_BODY, saveClip } from "@/lib/speechServer";

export const dynamic = "force-dynamic";

const BASE64 = /^[A-Za-z0-9+/]+={0,2}$/;

/**
 * POST /api/speech/clip {wav, text}: keep a clip of the user reading, in the vault on this
 * computer (state/speech/, readable only by them), which Listen's own voice is made from. `wav` is
 * 16-bit mono WAV at 24 kHz as base64, `text` what it says. {delete: true} deletes it, and stops
 * the speech server, which may hold what it made of it. The clip is never sent anywhere, nor
 * shown back.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req, MAX_CLIP_BODY);
  if ("denied" in parsed) return parsed.denied;
  const { wav, text } = parsed.body;
  if (parsed.body.delete === true) {
    const result = await deleteClip();
    return Response.json(result, { status: result.ok ? 200 : 500, headers: NO_STORE });
  }
  if (typeof wav !== "string" || !BASE64.test(wav)) return Response.json({ error: "expected a WAV, as base64" }, { status: 400 });
  if (text !== null && text !== undefined && typeof text !== "string") {
    return Response.json({ error: "text must be a string" }, { status: 400 });
  }
  const result = await saveClip(wav, typeof text === "string" ? text.slice(0, 2000) : null);
  return Response.json(result, { status: result.ok ? 200 : 422, headers: NO_STORE });
}
