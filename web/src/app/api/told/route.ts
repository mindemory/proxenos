import path from "node:path";

import { NO_STORE, readLocalJson, rejectNonLocal } from "@/lib/guard";
import { appendJsonl, nowIso, readJsonl, vaultPath, VaultMissingError } from "@/lib/vault";
import type { ToldNote } from "@/lib/types";

export const dynamic = "force-dynamic";

const MAX_CHARS = 1000;
const NOTES = ["state", "told.jsonl"];
/** How long a fact counts, as proxenos.told keeps it; a rule ("always") counts until removed. */
const FACT_DAYS = 14;

/** The notes that count now, as proxenos.told reads them: every rule, the recent facts, none removed. */
async function current(): Promise<ToldNote[]> {
  const lines = (await readJsonl(path.join(vaultPath(), ...NOTES)).catch(() => [])) as Record<string, unknown>[];
  const found = new Map<string, ToldNote>();
  const since = Date.now() - FACT_DAYS * 24 * 60 * 60 * 1000;
  for (const line of lines) {
    if (typeof line?.at !== "string" || Number.isNaN(Date.parse(line.at))) continue;
    if (typeof line.forget === "string") {
      found.delete(line.forget);
      continue;
    }
    const text = typeof line.text === "string" ? line.text.replace(/\s+/g, " ").trim() : "";
    const always = line.always === true;
    if (text && (always || Date.parse(line.at) >= since)) found.set(line.at, { at: line.at, text, always });
  }
  return [...found.values()].sort((a, b) => b.at.localeCompare(a.at));
}

/** GET /api/told: what the reader told Proxenos that still counts, newest first. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json({ notes: await current() }, { headers: NO_STORE });
}

/**
 * POST /api/told {"text", "always"} tells Proxenos something its messages don't show: a fact
 * for now, or with always a rule for everything it drafts. {"forget": at} removes one. Each is a
 * line appended to state/told.jsonl.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { text, always, forget } = parsed.body;
  let entry: Record<string, unknown>;
  if (typeof forget === "string" && !Number.isNaN(Date.parse(forget))) {
    entry = { at: nowIso(), forget };
  } else if (typeof text === "string" && text.trim() && text.length <= MAX_CHARS) {
    entry = { at: nowIso(), text: text.replace(/\s+/g, " ").trim(), always: always === true };
  } else {
    return Response.json({ error: `text must be 1 to ${MAX_CHARS} characters, or forget a note's at` }, { status: 400 });
  }
  try {
    await appendJsonl(NOTES, entry);
  } catch (e) {
    const status = e instanceof VaultMissingError ? 503 : 500;
    return Response.json({ error: "could not save the note" }, { status });
  }
  return Response.json({ notes: await current() }, { headers: NO_STORE });
}
