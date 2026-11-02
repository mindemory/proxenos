import { NO_STORE, readLocalJson, rejectNonLocal } from "@/lib/guard";
import { getLife, isMonth, startMonth } from "@/lib/life";

export const dynamic = "force-dynamic";

/**
 * GET /api/life: every month with records or a story, newest first, and how a month being written
 * stands; cheap enough to poll. GET /api/life?month=YYYY-MM adds that month's story and its days.
 */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  const month = new URL(req.url).searchParams.get("month");
  return Response.json(await getLife(isMonth(month) ? month : null), { headers: NO_STORE });
}

/** POST /api/life {month: "YYYY-MM"}: write that month's story now, in the background; the page follows it through GET. */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { month } = parsed.body;
  if (!isMonth(month)) return Response.json({ error: "month must be YYYY-MM." }, { status: 400 });
  const job = await startMonth(month);
  if (!job) return Response.json({ error: "A month is being written already." }, { status: 409 });
  return Response.json({ job }, { status: 202, headers: NO_STORE });
}
