import { NO_STORE, readLocalJson, rejectNonLocal } from "@/lib/guard";
import { actOnDoc, DOC_ACTIONS, readDoc, type DocAction } from "@/lib/manuscript";
import { isProjectId } from "@/lib/projects";

export const dynamic = "force-dynamic";

/**
 * GET /api/projects/gdocs?project=<id>: the project's manuscript as a Google Doc, as the vault
 * keeps it: the Google Docs sign-ins, the doc's link and where it came from, and its comments
 * (other people's words, shown here and never sent to a model). Nothing is fetched from Google.
 */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  const project = new URL(req.url).searchParams.get("project");
  if (!isProjectId(project)) return Response.json({ error: "project must be a project's id." }, { status: 400 });
  const read = await readDoc(project);
  return "error" in read ? Response.json({ error: read.error }, { status: read.status }) : Response.json(read.data, { headers: NO_STORE });
}

/**
 * POST /api/projects/gdocs {project, action} runs `proxenos project gdocs <id> <action>` and
 * answers when it's done. "open" makes the doc in the user's own Drive the first time, from the
 * manuscript at its branch's tip, and gives its link after; "fresh" makes a new one; "pull"
 * brings its changes back as a step waiting on the user, from the commit it was made from, and
 * reads its comments; "comments" reads them alone. Nothing is shared and nothing is deleted.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { project, action } = parsed.body;
  if (!isProjectId(project)) return Response.json({ error: "project must be a project's id." }, { status: 400 });
  if (!DOC_ACTIONS.includes(action as DocAction)) {
    return Response.json({ error: `action must be one of ${DOC_ACTIONS.join(", ")}.` }, { status: 400 });
  }
  const done = await actOnDoc(project, action as DocAction);
  return "error" in done ? Response.json({ error: done.error }, { status: done.status }) : Response.json(done.data, { headers: NO_STORE });
}
