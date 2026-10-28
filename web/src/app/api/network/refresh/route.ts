import { NO_STORE, readLocalJson } from "@/lib/guard";
import { rebuildPeople } from "@/lib/vault";

export const dynamic = "force-dynamic";

/** POST /api/network/refresh {} rebuilds people.json (`proxenos clone network --people-only`). */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  return Response.json(await rebuildPeople(), { headers: NO_STORE });
}
