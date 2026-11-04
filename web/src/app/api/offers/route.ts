import { NO_STORE, readLocalJson, rejectNonLocal } from "@/lib/guard";
import { getOffers, parseOffers, startOffers } from "@/lib/offers";

export const dynamic = "force-dynamic";

/** GET /api/offers: the comparisons, newest first, each row with its reply as its errand stands, and how the running one stands. Cheap enough to poll. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getOffers(), { headers: NO_STORE });
}

/**
 * POST /api/offers {goal, months?, project?} compares what each person or firm offered for the goal,
 * from the last 3, 6, 12 (the default) or 24 months of mail and chats, and writes a reply to each as
 * an errand that waits on its Send; with a project's id, the table goes into its brief too. It goes
 * to `proxenos clone offers` on its stdin and nowhere else, and is answered at once; the page
 * follows it through GET /api/offers.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req, 8192);
  if ("denied" in parsed) return parsed.denied;
  const request = parseOffers(parsed.body);
  if ("error" in request) return Response.json({ error: request.error }, { status: 400 });
  const job = await startOffers(request);
  if (!job) return Response.json({ error: "Another comparison is still being made." }, { status: 409 });
  return Response.json({ job }, { status: 202, headers: NO_STORE });
}
