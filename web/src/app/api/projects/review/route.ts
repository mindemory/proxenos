import { NO_STORE, readLocalJson, rejectNonLocal } from "@/lib/guard";
import { isProjectId } from "@/lib/projects";
import { getReviews, isRounds, startReview } from "@/lib/review";
import { REVIEW_ROUNDS_MAX } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * GET /api/projects/review?project=<id>: the project's peer reviews, newest first, as the vault
 * keeps them: each round's reports, the plan and the response letter, and what became of every
 * concern; and how the review job stands. Cheap enough to poll.
 */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  const project = new URL(req.url).searchParams.get("project");
  if (!isProjectId(project)) return Response.json({ error: "project must be a project's id." }, { status: 400 });
  return Response.json(await getReviews(project), { headers: NO_STORE });
}

/**
 * POST /api/projects/review {project, rounds} runs `proxenos review <id> --rounds <n>`: the
 * manuscript and its code go to the review model, the user having asked; the revision comes back
 * as the project's steps, waiting on them. One review at a time; the page follows it through GET.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { project, rounds } = parsed.body;
  if (!isProjectId(project)) return Response.json({ error: "project must be a project's id." }, { status: 400 });
  if (!isRounds(rounds)) return Response.json({ error: `rounds must be 1 to ${REVIEW_ROUNDS_MAX}.` }, { status: 400 });
  const job = await startReview(project, rounds);
  if (!job) return Response.json({ error: "A review is already going: one at a time." }, { status: 409 });
  return Response.json({ job }, { status: 202, headers: NO_STORE });
}
