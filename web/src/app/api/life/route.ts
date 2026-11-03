import { NO_STORE, readLocalJson, rejectNonLocal } from "@/lib/guard";
import {
  getLife,
  isEdited,
  isItem,
  isMonth,
  mark,
  MAX_CORRECTION,
  MAX_ESSAY,
  MAX_MARKED,
  MAX_SUMMARY,
  saveEdit,
  startMonth,
} from "@/lib/life";
import { VaultMissingError } from "@/lib/vault";

export const dynamic = "force-dynamic";

/**
 * GET /api/life: every month with records or a story, newest first, and how a month being written
 * stands; cheap enough to poll. GET /api/life?month=YYYY-MM adds that month's diary, what was marked
 * not true in it, and its days.
 */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  const month = new URL(req.url).searchParams.get("month");
  return Response.json(await getLife(isMonth(month) ? month : null), { headers: NO_STORE });
}

function text(v: unknown, max: number): string | null {
  return typeof v === "string" && v.length <= max ? v : null;
}

/**
 * POST /api/life, one of:
 * - {month: "YYYY-MM"}: write that month's diary now, in the background; the page follows it through GET.
 *   A month whose abstract and essay are the user's own is written again only with {again: true}, which
 *   the page sends once they've said so: it writes from their text, then shows its own.
 * - {month, edit: {summary, essay}}: keep the user's own abstract and essay, which the night never writes over.
 * - {month, mark: {item, text, correction?}}: what the item ("essay", a paragraph of it, "highlight" or
 *   "entry:YYYY-MM-DD") said isn't true, and what is in the user's words; {month, unmark: {item, text}} takes it back.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { month, edit, mark: marking, unmark, again } = parsed.body;
  if (!isMonth(month)) return Response.json({ error: "month must be YYYY-MM." }, { status: 400 });

  if (edit !== undefined || marking !== undefined || unmark !== undefined) {
    try {
      if (edit !== undefined) {
        const e = (edit ?? {}) as Record<string, unknown>;
        const summary = text(e.summary, MAX_SUMMARY);
        const essay = text(e.essay, MAX_ESSAY);
        if (summary === null || essay === null || !(summary.trim() || essay.trim())) {
          return Response.json(
            { error: `An abstract of up to ${MAX_SUMMARY} characters and an essay of up to ${MAX_ESSAY}, not both empty.` },
            { status: 400 },
          );
        }
        return Response.json({ story: await saveEdit(month, summary, essay) }, { headers: NO_STORE });
      }
      const m = ((marking ?? unmark) ?? {}) as Record<string, unknown>;
      const said = text(m.text, MAX_MARKED);
      const correction = m.correction === undefined ? "" : text(m.correction, MAX_CORRECTION);
      if (!isItem(m.item, month) || !said?.trim() || correction === null) {
        return Response.json(
          { error: `Mark a paragraph, a highlight or an entry of this month, with up to ${MAX_CORRECTION} characters of what's true.` },
          { status: 400 },
        );
      }
      const corrections = await mark(month, m.item, said, correction, unmark !== undefined);
      return Response.json({ corrections }, { headers: NO_STORE });
    } catch (e) {
      const status = e instanceof VaultMissingError ? 503 : 500;
      return Response.json({ error: "Couldn't save it." }, { status });
    }
  }

  if (again !== true && (await isEdited(month))) {
    return Response.json({ error: "This month's abstract and essay are your own. Say to write it again from them." }, { status: 409 });
  }
  const job = await startMonth(month);
  if (!job) return Response.json({ error: "A month is being written already." }, { status: 409 });
  return Response.json({ job }, { status: 202, headers: NO_STORE });
}
