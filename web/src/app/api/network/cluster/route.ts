import { NO_STORE, readLocalJson } from "@/lib/guard";
import { CLUSTER_LABEL_CHARS } from "@/lib/clusters";
import { ClusterNotFoundError, rebuildPeople, renameCluster, VaultMissingError } from "@/lib/vault";

export const dynamic = "force-dynamic";

/**
 * POST /api/network/cluster {"id", "label"} names a cluster as the user would, in
 * clones/network/clusters.json, then rebuilds people.json with it. An empty label drops the
 * user's name, so the model's or the group's comes back. The answer says whether the rebuild ran.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { id, label } = parsed.body;
  if (typeof id !== "number" || !Number.isInteger(id) || id <= 0) {
    return Response.json({ error: "invalid id" }, { status: 400 });
  }
  if (typeof label !== "string" || label.trim().length > CLUSTER_LABEL_CHARS || /[\r\n]/.test(label)) {
    return Response.json({ error: `a name is one line of at most ${CLUSTER_LABEL_CHARS} characters` }, { status: 400 });
  }

  try {
    await renameCluster(id, label);
  } catch (e) {
    if (e instanceof VaultMissingError) {
      return Response.json({ error: `vault not found at ${e.message}` }, { status: 503 });
    }
    if (e instanceof ClusterNotFoundError) {
      return Response.json({ error: "no such cluster in people.json" }, { status: 404 });
    }
    return Response.json({ error: "could not save that" }, { status: 500 });
  }
  return Response.json(await rebuildPeople(), { headers: NO_STORE });
}
