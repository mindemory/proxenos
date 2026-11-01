import { NO_STORE, readLocalJson, rejectNonLocal } from "@/lib/guard";
import { isRev, readManuscript, readStepChanges, startEdit } from "@/lib/manuscript";
import { isBranch, isProjectId, isRepoPath, isStepId } from "@/lib/projects";
import { MANUSCRIPT_MAX_TEXT } from "@/lib/types";

export const dynamic = "force-dynamic";

// The longest text at its longest with every character escaped, and room for the rest.
const MAX_BODY = MANUSCRIPT_MAX_TEXT * 6 + 4096;

/**
 * GET /api/projects/manuscript?project=<id>[&base=<rev>&head=<rev>]: the project's manuscript, its
 * versions, and the head version's text with its changes since the base (by default the newest
 * against the one before). With &step=<project>/<when> instead: every file that step changed.
 * Read from the project's code with git, never from the user's checkout.
 */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  const url = new URL(req.url);
  const project = url.searchParams.get("project");
  if (!isProjectId(project)) return Response.json({ error: "project must be a project's id." }, { status: 400 });
  const step = url.searchParams.get("step");
  if (step !== null) {
    if (!isStepId(step) || !step.startsWith(`${project}/`)) return Response.json({ error: "step must be one of its steps." }, { status: 400 });
    const read = await readStepChanges(project, step);
    return "error" in read ? Response.json({ error: read.error }, { status: read.status }) : Response.json(read.data, { headers: NO_STORE });
  }
  const base = url.searchParams.get("base") || undefined;
  const head = url.searchParams.get("head") || undefined;
  if ((base && !isRev(base)) || (head && !isRev(head))) return Response.json({ error: "A version is a commit or a branch." }, { status: 400 });
  const read = await readManuscript(project, base, head);
  return "error" in read ? Response.json({ error: read.error }, { status: read.status }) : Response.json(read.data, { headers: NO_STORE });
}

/**
 * POST /api/projects/manuscript {edit: <project>, path, branch, from, text} saves the user's own
 * text for the manuscript: `proxenos project manuscript --edit` commits it on a new branch made
 * from the manuscript's branch at `from`, apart from the user's checkout, and records it as a step
 * waiting on them, which Accept merges and Discard deletes. The text goes on the command's stdin.
 * Answered at once; the page follows it through GET /api/projects, as the job "decide".
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req, MAX_BODY);
  if ("denied" in parsed) return parsed.denied;
  const body = parsed.body;
  if (!isProjectId(body.edit)) return Response.json({ error: "edit must be a project's id." }, { status: 400 });
  if (!isRepoPath(body.path) || !isBranch(body.branch)) return Response.json({ error: "Say which file and branch." }, { status: 400 });
  if (body.branch.startsWith("proxenos/")) return Response.json({ error: "Edit the manuscript's own branch." }, { status: 400 });
  if (!/^[0-9a-f]{40,64}$/.test(typeof body.from === "string" ? body.from : "")) {
    return Response.json({ error: "from must be the commit the text was read at." }, { status: 400 });
  }
  if (typeof body.text !== "string" || body.text.length > MANUSCRIPT_MAX_TEXT) {
    return Response.json({ error: `Send the text, up to ${MANUSCRIPT_MAX_TEXT.toLocaleString("en-US")} characters.` }, { status: 400 });
  }
  const job = await startEdit(body.edit, { path: body.path, branch: body.branch, from: body.from as string, text: body.text });
  if (!job) return Response.json({ error: "The last one is still going." }, { status: 409 });
  return Response.json({ job }, { status: 202, headers: NO_STORE });
}
