import { ERRAND_MAX_BODY, getErrands, isErrandId, parseGoal, parseSend, startErrand, startSend } from "@/lib/errands";
import { NO_STORE, readLocalJson, rejectNonLocal } from "@/lib/guard";

export const dynamic = "force-dynamic";

/** GET /api/errands: the newest errands, newest first, and how the running one stands. Cheap enough to poll. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getErrands(), { headers: NO_STORE });
}

/**
 * POST /api/errands {goal} carries out a new errand, up to 2,000 characters. {send: <id>, index,
 * address?, subject?, body?} sends that one of its messages, with the edits made first: the only
 * way anything an errand wrote goes out. {drop: <id>} drops the errand. Each goes to `proxenos
 * clone errands` on its stdin and nowhere else, and is answered at once; the page follows it through
 * GET /api/errands.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req, ERRAND_MAX_BODY);
  if ("denied" in parsed) return parsed.denied;
  const body = parsed.body;
  let job;
  if ("send" in body) {
    const send = parseSend(body);
    if ("error" in send) return Response.json({ error: send.error }, { status: 400 });
    job = await startSend(send);
  } else if ("drop" in body) {
    if (!isErrandId(body.drop)) return Response.json({ error: "drop must be an errand's id." }, { status: 400 });
    job = await startSend({ drop: body.drop });
  } else {
    const goal = parseGoal(body);
    if (typeof goal !== "string") return Response.json({ error: goal.error }, { status: 400 });
    job = await startErrand(goal);
  }
  if (!job) {
    const busy = "goal" in body ? "Another errand is still being carried out." : "A Send is still going.";
    return Response.json({ error: busy }, { status: 409 });
  }
  return Response.json({ job }, { status: 202, headers: NO_STORE });
}
