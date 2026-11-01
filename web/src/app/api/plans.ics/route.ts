import { readFile } from "node:fs/promises";
import path from "node:path";

import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { vaultPath } from "@/lib/vault";

export const dynamic = "force-dynamic";

const EMPTY = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Proxenos//Plans//EN\r\nX-WR-CALNAME:Proxenos\r\nEND:VCALENDAR\r\n";

/**
 * GET /api/plans.ics: the tasks with a set time as a calendar to subscribe to, from
 * clones/tasks/plans.ics, which each run of the tasks clone writes (proxenos.plans). Before
 * the first, an empty calendar, so a subscription made early still works.
 */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  const text = await readFile(path.join(vaultPath(), "clones", "tasks", "plans.ics"), "utf8").catch(() => EMPTY);
  return new Response(text, {
    headers: { ...NO_STORE, "Content-Type": "text/calendar; charset=utf-8", "Content-Disposition": 'inline; filename="proxenos.ics"' },
  });
}
