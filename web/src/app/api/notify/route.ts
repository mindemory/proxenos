import { NO_STORE, readLocalJson } from "@/lib/guard";
import { sendTestNotice } from "@/lib/notify";

export const dynamic = "force-dynamic";

/**
 * POST /api/notify {test: true}: one test notice to the phone through ntfy, by `proxenos notify
 * test`. Answers {ok, message}: whether it got through, and if not, why. The topic and token
 * stay with the command; neither is in the request or the answer.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  if (parsed.body.test !== true) return Response.json({ error: "Nothing to do." }, { status: 400 });
  const result = await sendTestNotice();
  return Response.json(result, { status: result.ok ? 200 : 422, headers: NO_STORE });
}
