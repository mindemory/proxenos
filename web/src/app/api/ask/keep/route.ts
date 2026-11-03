import { isAskId, isOpeningId, keepOpening } from "@/lib/ask";
import { NO_STORE, readLocalJson } from "@/lib/guard";

export const dynamic = "force-dynamic";

/**
 * POST /api/ask/keep {ask, opening}: keep an opening an ask showed among those the week's choices
 * weigh (`proxenos ask --keep`). Only the ids are taken from the request: what's kept is read from
 * the ask's own file. Keeping one twice keeps it once. Nothing is applied for or sent.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { ask, opening } = parsed.body;
  if (!isAskId(ask)) return Response.json({ error: "ask must be an ask's id." }, { status: 400 });
  if (!isOpeningId(opening)) return Response.json({ error: "opening must be an opening's id." }, { status: 400 });
  const kept = await keepOpening(ask, opening);
  if (!kept.ok) return Response.json({ error: kept.message }, { status: 500, headers: NO_STORE });
  return Response.json({ ok: true, message: kept.message }, { headers: NO_STORE });
}
