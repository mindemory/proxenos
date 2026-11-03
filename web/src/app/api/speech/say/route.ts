import { NO_STORE, readLocalJson } from "@/lib/guard";
import { ENGINES, MAX_SAY, say } from "@/lib/speechServer";
import type { SpeechEngine } from "@/lib/types";

export const dynamic = "force-dynamic";

const VOICE = /^[a-z_]{1,30}$/;

/**
 * POST /api/speech/say {text, engine, voice}: a sentence or two spoken by a voice made on this
 * Mac, as a WAV. Any error says why, and Listen then reads with the device's own voice. The text
 * goes to the speech server on 127.0.0.1 and nowhere else, and isn't kept or logged.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req, 16 * 1024);
  if ("denied" in parsed) return parsed.denied;
  const { text, engine, voice } = parsed.body;
  if (typeof text !== "string" || !text.trim() || text.length > MAX_SAY) {
    return Response.json({ error: `text must be 1 to ${MAX_SAY} characters` }, { status: 400 });
  }
  if (!ENGINES.includes(engine as SpeechEngine)) return Response.json({ error: "unknown engine" }, { status: 400 });
  if (voice !== null && voice !== undefined && !(typeof voice === "string" && VOICE.test(voice))) {
    return Response.json({ error: "unknown voice" }, { status: 400 });
  }
  const result = await say(text, engine as SpeechEngine, typeof voice === "string" ? voice : null, req.signal);
  if ("error" in result) return Response.json({ error: result.error }, { status: result.status, headers: NO_STORE });
  return new Response(result.audio, { headers: { "Content-Type": "audio/wav", ...NO_STORE } });
}
