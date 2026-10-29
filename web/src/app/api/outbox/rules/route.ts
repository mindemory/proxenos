import { NO_STORE, readLocalJson } from "@/lib/guard";
import { parseOutboxEdit } from "@/lib/outbox";
import { saveOutboxRules, VaultMissingError } from "@/lib/vault";

export const dynamic = "force-dynamic";

/**
 * POST /api/outbox/rules, one change at a time:
 *   {"enabled": boolean}
 *   {"daily_limit": integer 1..50}
 *   {"channel": email|whatsapp|slack|instagram|messenger|x|linkedin, "on"?: boolean,
 *    "min_closeness"?: number 0.5..1, "min_measured"?: integer 1..100}
 * Anything else is refused. The change is merged into clones/outbox/rules.json (its defaults where
 * the file lacks them) and the answer is the rules as saved. The sync reads that file; this only
 * says what may go out.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const checked = parseOutboxEdit(parsed.body);
  if ("error" in checked) return Response.json({ error: checked.error }, { status: 400 });

  try {
    const rules = await saveOutboxRules(checked.edit);
    return Response.json({ ok: true, rules }, { headers: NO_STORE });
  } catch (e) {
    if (e instanceof VaultMissingError) {
      return Response.json({ error: `vault not found at ${e.message}` }, { status: 503 });
    }
    return Response.json({ error: "could not save the rules" }, { status: 500 });
  }
}
