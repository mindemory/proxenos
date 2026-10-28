import { NO_STORE, readLocalJson } from "@/lib/guard";
import { PEOPLE_EDITS, type PeopleEdit } from "@/lib/types";
import { editPeople, PersonNotFoundError, rebuildPeople, VaultMissingError } from "@/lib/vault";

export const dynamic = "force-dynamic";

const PERSON_ID = /^[0-9a-f]{12}$/;

/**
 * POST /api/network/people {"action": "same" | "different" | "hide", "id", "other"?, "name"?}
 * records who is who in clones/network/aliases.json, then rebuilds people.json with it. same
 * and different take another person's id as "other"; different can instead take "name", one of
 * the names this person was merged from. The answer says whether the rebuild ran; when it
 * didn't, the edit is saved for the next one.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { action, id, other, name } = parsed.body;
  if (typeof action !== "string" || !PEOPLE_EDITS.includes(action as PeopleEdit)) {
    return Response.json({ error: `action must be one of ${PEOPLE_EDITS.join(", ")}` }, { status: 400 });
  }
  if (typeof id !== "string" || !PERSON_ID.test(id)) {
    return Response.json({ error: "invalid id" }, { status: 400 });
  }
  const byName = action === "different" && other === undefined;
  if (byName && (typeof name !== "string" || !name.trim() || name.length > 120 || /[\r\n]/.test(name))) {
    return Response.json({ error: "different needs another person's id or a name" }, { status: 400 });
  }
  const pair = action !== "hide" && !byName;
  if (pair && (typeof other !== "string" || !PERSON_ID.test(other) || other === id)) {
    return Response.json({ error: "same and different need another person's id" }, { status: 400 });
  }

  try {
    const target = byName ? { name: name as string } : pair ? { id: other as string } : undefined;
    await editPeople(action as PeopleEdit, id, target);
  } catch (e) {
    if (e instanceof VaultMissingError) {
      return Response.json({ error: `vault not found at ${e.message}` }, { status: 503 });
    }
    if (e instanceof PersonNotFoundError) {
      return Response.json({ error: "no such person in people.json" }, { status: 404 });
    }
    return Response.json({ error: "could not save that" }, { status: 500 });
  }
  return Response.json(await rebuildPeople(), { headers: NO_STORE });
}
