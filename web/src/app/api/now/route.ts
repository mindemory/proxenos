import { NO_STORE, readLocalJson, rejectNonLocal } from "@/lib/guard";
import { appendJsonl, nowIso, readJsonl, vaultPath, VaultMissingError } from "@/lib/vault";
import path from "node:path";

export const dynamic = "force-dynamic";

/** The most a "right now" note may hold. */
const MAX_CHARS = 1000;
const NOTES = ["state", "now.jsonl"];

/** GET /api/now: the newest "right now" note, {text, at}, or {text: "", at: null}. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  const notes = await readJsonl(path.join(vaultPath(), ...NOTES)).catch(() => []);
  const last = notes.at(-1) as { text?: unknown; at?: unknown } | undefined;
  const text = typeof last?.text === "string" ? last.text : "";
  const at = typeof last?.at === "string" && text ? last.at : null;
  return Response.json({ text, at }, { headers: NO_STORE });
}

/**
 * POST /api/now {"text"} saves how the reader is right now, for the next drafts to take into
 * account. An empty text clears it. Appended to state/now.jsonl, so earlier notes stay.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { text } = parsed.body;
  if (typeof text !== "string" || text.length > MAX_CHARS) {
    return Response.json({ error: `text must be a string of at most ${MAX_CHARS} characters` }, { status: 400 });
  }
  const entry = { at: nowIso(), text: text.replace(/\s+/g, " ").trim() };
  try {
    await appendJsonl(NOTES, entry);
  } catch (e) {
    const status = e instanceof VaultMissingError ? 503 : 500;
    return Response.json({ error: "could not save the note" }, { status });
  }
  return Response.json(entry, { headers: NO_STORE });
}
