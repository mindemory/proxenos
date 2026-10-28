// What the Home briefing adds to /api/home: today's agenda, activity per source over the last
// 30 days, and how drafts have been reviewed. Server only.

import { promises as fs } from "node:fs";
import path from "node:path";

import { memoryActivity } from "./memory";
import type { AgendaEvent, BriefingResponse } from "./types";
import { getDraftReviews, nowIso, vaultPath } from "./vault";

const MAX_RECALL_BYTES = 8 * 1024 * 1024;
const ACTIVITY_DAYS = 30;

function text(v: unknown): string {
  return typeof v === "string" ? v : "";
}

/**
 * Upcoming events from clones/recall/today.json. The recall clone writes every event in its
 * 48-hour window to "events"; a file from before it did only has the events that brought
 * memories to mind, among its triggers.
 */
async function agenda(vault: string): Promise<BriefingResponse["agenda"]> {
  const file = path.join(vault, "clones", "recall", "today.json");
  let data: Record<string, unknown>;
  try {
    const st = await fs.stat(file);
    if (st.size > MAX_RECALL_BYTES) return { exists: false, generated: null, events: [] };
    const parsed: unknown = JSON.parse(await fs.readFile(file, "utf8"));
    data = parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : {};
  } catch {
    return { exists: false, generated: null, events: [] };
  }
  const raw = Array.isArray(data.events)
    ? data.events
    : (Array.isArray(data.triggers) ? data.triggers : []).filter(
        (t) => t && typeof t === "object" && (t as Record<string, unknown>).kind === "event",
      );
  const events: AgendaEvent[] = [];
  for (const e of raw) {
    if (!e || typeof e !== "object") continue;
    const r = e as Record<string, unknown>;
    const title = text(r.title).trim();
    const when = text(r.when);
    if (!title || Number.isNaN(Date.parse(when))) continue;
    events.push({ title: title.slice(0, 300), when, all_day: r.all_day === true });
  }
  events.sort((a, b) => a.when.localeCompare(b.when));
  return { exists: true, generated: text(data.generated) || null, events: events.slice(0, 50) };
}

export async function getBriefing(): Promise<BriefingResponse> {
  const vault = vaultPath();
  const [events, review] = await Promise.all([agenda(vault), getDraftReviews(vault)]);
  let activity: BriefingResponse["activity"];
  try {
    activity = memoryActivity(ACTIVITY_DAYS);
  } catch {
    activity = { indexed: false, days: [], series: [] };
  }
  return { now: nowIso(), agenda: events, activity, reviews: review };
}
