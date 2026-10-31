import { NO_STORE, readLocalJson, rejectNonLocal } from "@/lib/guard";
import { getProjects, isProjectId, parseDecision, startDecision, startStep } from "@/lib/projects";
import { STEP_MAX_TEXT } from "@/lib/types";

export const dynamic = "force-dynamic";

// A queued step at its longest with every character escaped, and room for the rest.
const MAX_BODY = STEP_MAX_TEXT * 6 + 1024;

/** GET /api/projects: each project, where it stands, its queue and its newest steps, and how the jobs stand. Cheap enough to poll. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json(await getProjects(), { headers: NO_STORE });
}

/**
 * POST /api/projects {take: <project>} takes a step on that project now. {accept: <step>} merges
 * the step's branch into the user's checkout, the one request that changes their code; {discard:
 * <step>} deletes its branch and worktree. {queue: <project>, step} asks for a step, up to 2,000
 * characters, and {unqueue: <project>, id} takes one back. Each goes to `proxenos clone steps` on
 * its stdin and nowhere else, and is answered at once; the page follows it through GET.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req, MAX_BODY);
  if ("denied" in parsed) return parsed.denied;
  const body = parsed.body;
  let job;
  if ("take" in body) {
    if (!isProjectId(body.take)) return Response.json({ error: "take must be a project's id." }, { status: 400 });
    job = await startStep(body.take);
    if (!job) return Response.json({ error: "A step is already being taken: one at a time." }, { status: 409 });
  } else {
    const decision = parseDecision(body);
    if ("error" in decision) return Response.json({ error: decision.error }, { status: 400 });
    job = await startDecision(decision);
    if (!job) return Response.json({ error: "The last one is still going." }, { status: 409 });
  }
  return Response.json({ job }, { status: 202, headers: NO_STORE });
}
