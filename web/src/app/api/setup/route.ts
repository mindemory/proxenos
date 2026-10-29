import { NO_STORE, readLocalJson, rejectNonLocal } from "@/lib/guard";
import { applySetup, getSetup, parseChange } from "@/lib/setup";

export const dynamic = "force-dynamic";

/** GET /api/setup: the settings, the model, and which secrets are set and where each comes from. Never a secret. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getSetup(), { headers: NO_STORE });
}

/**
 * POST /api/setup makes one change: {settings: {name, vault, ...}}, {key} (an Anthropic API key,
 * checked with one call, then kept), {ollama: model}, {secret: NAME, value} or {forget: NAME}. A
 * key or token goes to `proxenos setup --apply` on its stdin and nowhere else; no answer from
 * here holds one. Answers with what was done and the new status, or why not.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const change = parseChange(parsed.body);
  if ("error" in change) return Response.json({ error: change.error }, { status: 400 });
  const result = await applySetup(change);
  return Response.json(result, { status: result.ok ? 200 : 422, headers: NO_STORE });
}
