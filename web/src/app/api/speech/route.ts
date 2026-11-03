import { NO_STORE, readLocalJson, rejectNonLocal } from "@/lib/guard";
import { ENGINES, getModel, speechStatus, warm } from "@/lib/speechServer";
import type { SpeechEngine } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * GET /api/speech: whether this Mac can make Listen's natural voice and the user's own, what each
 * still needs, the voices, the clip (how long and when, never its sound) and any download going.
 * Cheap enough to poll while a model downloads.
 */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await speechStatus(), { headers: NO_STORE });
}

/**
 * POST /api/speech {get: "natural" | "own"}: download that engine's model, once; GET follows it.
 * {warm: "natural" | "own", voice}: start the speech server with that engine (and natural voice)
 * loaded, as a view with Listen opens, so its first sentence comes quickly.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  if (ENGINES.includes(parsed.body.warm as SpeechEngine)) {
    const voice = typeof parsed.body.voice === "string" && /^[a-z_]{1,30}$/.test(parsed.body.voice) ? parsed.body.voice : null;
    const ok = await warm(parsed.body.warm as SpeechEngine, voice);
    return Response.json({ ok }, { status: ok ? 202 : 503, headers: NO_STORE });
  }
  const engine = parsed.body.get;
  if (!ENGINES.includes(engine as SpeechEngine)) return Response.json({ error: "Nothing to get." }, { status: 400 });
  const result = await getModel(engine as SpeechEngine);
  return Response.json(result, { status: result.ok ? 202 : 409, headers: NO_STORE });
}
