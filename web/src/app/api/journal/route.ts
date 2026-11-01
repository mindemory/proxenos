import { NO_STORE, readLocalJson, rejectNonLocal } from "@/lib/guard";
import { getJournal, writeJournalToday } from "@/lib/vault";

export const dynamic = "force-dynamic";

/** GET /api/journal (the newest day) or /api/journal?date=YYYY-MM-DD, plus every day there is. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  const date = new URL(req.url).searchParams.get("date");
  return Response.json(await getJournal(date && /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : null), {
    headers: NO_STORE,
  });
}

/** POST /api/journal {}: write today's entry now, then answer with it. */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const written = await writeJournalToday();
  if (!written.ok) return Response.json({ error: written.message }, { status: 500 });
  return Response.json(await getJournal(null), { headers: NO_STORE });
}
