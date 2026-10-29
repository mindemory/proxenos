import { startJob } from "@/lib/connect";
import { NO_STORE, readLocalJson } from "@/lib/guard";

export const dynamic = "force-dynamic";

const MAX_TOKEN = 4096;

/**
 * POST /api/connect/beeper {token} starts `proxenos auth beeper`, which checks the token against
 * Beeper Desktop and saves it. The token goes to the command on its stdin and nowhere else: not
 * its arguments, its environment, a log, or any answer from here. Answers at once; the page
 * follows the check through /api/connect/jobs.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const token = typeof parsed.body.token === "string" ? parsed.body.token.trim() : "";
  if (!token || token.length >= MAX_TOKEN || /[\r\n\0]/.test(token)) {
    return Response.json({ error: "That doesn't look like a Beeper token. Copy it again from Beeper." }, { status: 400 });
  }
  const job = await startJob("beeper", ["auth", "beeper"], null, `${token}\n`);
  if (!job) return Response.json({ error: "A token is already being checked." }, { status: 409 });
  return Response.json({ job }, { status: 202, headers: NO_STORE });
}
