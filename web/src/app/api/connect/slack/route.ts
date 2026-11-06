import { startJob } from "@/lib/connect";
import { NO_STORE, readLocalJson } from "@/lib/guard";

export const dynamic = "force-dynamic";

/** A Slack workspace's name as it appears before .slack.com. */
const WORKSPACE = /^[a-z0-9][a-z0-9-]{0,62}$/;

/**
 * POST /api/connect/slack {workspace} starts `proxenos auth slackdump NAME`: slackdump is downloaded
 * first when there's none (from its GitHub release), then a browser window opens on Slack's login
 * page, and once the person has signed in the workspace's last 30 days are saved. Answers at once;
 * the page follows it through /api/connect/jobs, which shows the command's latest line.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { workspace } = parsed.body;
  if (typeof workspace !== "string" || !WORKSPACE.test(workspace)) {
    return Response.json({ error: "Name the workspace as in its address, like acme for acme.slack.com." }, { status: 400 });
  }
  // "--" so nothing in the name is taken for an option.
  const job = await startJob("slack", ["auth", "slackdump", "--", workspace], workspace);
  if (!job) return Response.json({ error: "A Slack sign-in is already going." }, { status: 409 });
  return Response.json({ job }, { status: 202, headers: NO_STORE });
}
