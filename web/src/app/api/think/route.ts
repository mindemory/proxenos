import { NO_STORE, readLocalJson, rejectNonLocal } from "@/lib/guard";
import { getThink, isThreadId, parseSay, startThink, thinkJob, THINK_MAX_BODY } from "@/lib/think";
import { nowIso } from "@/lib/vault";

export const dynamic = "force-dynamic";

/**
 * GET /api/think: every thread, newest first, and how the latest `proxenos think` stands.
 * ?id=<thread> adds that thread, whole. ?job=1 is the job alone, with no command run, cheap enough
 * to poll while Proxenos thinks.
 */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  const params = new URL(req.url).searchParams;
  if (params.get("job") === "1") return Response.json({ now: nowIso(), job: thinkJob() }, { headers: NO_STORE });
  const id = params.get("id");
  return Response.json(await getThink(isThreadId(id) ? id : null), { headers: NO_STORE });
}

/**
 * POST /api/think {text, thread?, context?: {kind, id, text?}} starts `proxenos think` on a
 * message: up to 8,000 characters, to a thread, or to a new one that may start from a draft, a
 * project, a day, a person or a note. An empty text to a thread asks for its last answer again.
 * The message goes to the command on its stdin and nowhere else. Answers at once; the page follows
 * the job through GET ?job=1.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req, THINK_MAX_BODY);
  if ("denied" in parsed) return parsed.denied;
  const say = parseSay(parsed.body);
  if ("error" in say) return Response.json({ error: say.error }, { status: 400 });
  const job = await startThink(say);
  if (!job) return Response.json({ error: "Proxenos is still thinking something else through." }, { status: 409 });
  return Response.json({ job }, { status: 202, headers: NO_STORE });
}
