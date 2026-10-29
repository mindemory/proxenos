import { ASK_MAX_BODY, getAsks, isAskId, parseAsk, startAgain, startAsk } from "@/lib/ask";
import { NO_STORE, readLocalJson, rejectNonLocal } from "@/lib/guard";

export const dynamic = "force-dynamic";

/** GET /api/ask: the twenty newest asks, newest first, and how the ask running now stands. Cheap enough to poll. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getAsks(), { headers: NO_STORE });
}

/**
 * POST /api/ask {text, images: [{type, data}], deep} starts `proxenos ask` on a question: up to
 * 8,000 characters and up to four screenshots (PNG, JPEG or WebP as base64, 6 MB each), at least
 * one of the two; a quick answer unless `deep` is true. {again: <id>} thinks an earlier quick ask
 * through instead. The question goes to the command on its stdin and nowhere else: not its
 * arguments, its environment, a log, or any answer from here. Answers at once; the page follows the
 * ask through GET /api/ask. A route handler has no limit on its body of its own, so readLocalJson
 * is given one.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req, ASK_MAX_BODY);
  if ("denied" in parsed) return parsed.denied;
  let job;
  if ("again" in parsed.body) {
    if (!isAskId(parsed.body.again)) return Response.json({ error: "again must be an ask's id." }, { status: 400 });
    job = await startAgain(parsed.body.again);
  } else {
    const question = parseAsk(parsed.body);
    if ("error" in question) return Response.json({ error: question.error }, { status: 400 });
    job = await startAsk(question);
  }
  if (!job) return Response.json({ error: "Another question is still being thought through." }, { status: 409 });
  return Response.json({ job }, { status: 202, headers: NO_STORE });
}
