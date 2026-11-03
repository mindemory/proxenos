import { getCompare, isPick, isRoundId, parseModel, pickCompare, startCompare, stopCompare } from "@/lib/compare";
import { NO_STORE, readLocalJson, rejectNonLocal } from "@/lib/guard";
import { COMPARE_MAX_ROUND, COMPARE_ROUND } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * GET /api/compare: the newest round comparing two models (?round=<id> for another), each reply blind until it's
 * been picked, how each model fared, and how a round being drafted stands. Polled while one is.
 */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  const round = new URL(req.url).searchParams.get("round");
  return Response.json(await getCompare(isRoundId(round) ? round : null), { headers: NO_STORE });
}

/**
 * POST /api/compare {model, n?} drafts a new round in the background, `model` against the drafting model set up, and
 * answers at once; {round, item, pick} picks for one reply ("A", "B", "both" or "neither") and answers with the round;
 * {stop: true} stops the round being drafted. Nothing is sent to anyone.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const body = parsed.body;
  if (body.stop === true) {
    return Response.json({ stopped: stopCompare() }, { headers: NO_STORE });
  }
  if ("pick" in body) {
    const { round, item, pick } = body;
    if (!isRoundId(round)) return Response.json({ error: "round must be a round's id." }, { status: 400 });
    if (typeof item !== "number" || !Number.isInteger(item) || item < 1 || item > COMPARE_MAX_ROUND) {
      return Response.json({ error: "item must be a reply's number." }, { status: 400 });
    }
    if (!isPick(pick)) return Response.json({ error: "pick must be A, B, both or neither." }, { status: 400 });
    const answer = await pickCompare(round, item, pick);
    return Response.json(answer, { status: answer.error ? 409 : 200, headers: NO_STORE });
  }
  const model = parseModel(body.model);
  if (!model) return Response.json({ error: "Name a model, e.g. ollama:gemma4:26b." }, { status: 400 });
  const n = body.n ?? COMPARE_ROUND;
  if (typeof n !== "number" || !Number.isInteger(n) || n < 1 || n > COMPARE_MAX_ROUND) {
    return Response.json({ error: `n must be 1 to ${COMPARE_MAX_ROUND}.` }, { status: 400 });
  }
  const job = await startCompare(model, n);
  if (!job) return Response.json({ error: "A round is being drafted already." }, { status: 409 });
  return Response.json({ job }, { status: 202, headers: NO_STORE });
}
