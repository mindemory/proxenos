import { startJob, stopJob } from "@/lib/connect";
import { NO_STORE, readLocalJson, rejectNonLocal } from "@/lib/guard";
import { makeArgs } from "@/lib/makeCommands";
import { runJob } from "@/lib/runJobs";

export const dynamic = "force-dynamic";

/** GET /api/make: the latest view made on demand, running or how it ended, with the command it ran. Cheap enough to poll. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json({ job: runJob("make") }, { headers: NO_STORE });
}

/**
 * POST /api/make {command} runs one of the commands an empty view shows (lib/makeCommands.ts: the
 * exact line, and nothing else) in the background, one at a time, and answers at once. Nothing is
 * sent to anyone: they read the vault and write under it.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { command } = parsed.body;
  const args = makeArgs(command);
  if (!args || typeof command !== "string") {
    return Response.json({ error: "That isn't something the page can make." }, { status: 400 });
  }
  const job = await startJob("make", [...args], command);
  if (!job) return Response.json({ error: "Something is being made already." }, { status: 409 });
  return Response.json({ job: runJob("make") }, { status: 202, headers: NO_STORE });
}

/** DELETE /api/make stops the one being made. */
export async function DELETE(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json({ stopped: stopJob("make") }, { headers: NO_STORE });
}
