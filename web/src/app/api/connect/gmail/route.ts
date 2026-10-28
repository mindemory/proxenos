import { isAddress } from "@/lib/actions";
import { startJob } from "@/lib/connect";
import { NO_STORE, readLocalJson } from "@/lib/guard";

export const dynamic = "force-dynamic";

/** GMAIL_<NAME>: a short name for the account. */
const NAME = /^[A-Za-z0-9_]{1,32}$/;

/**
 * POST /api/connect/gmail {name, address} starts `proxenos auth gmail NAME ADDRESS`, which opens
 * Google's consent page in the browser and saves the token to .env. Answers at once; the page
 * follows the sign-in through /api/connect/jobs.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { name, address } = parsed.body;
  if (typeof name !== "string" || !NAME.test(name)) {
    return Response.json({ error: "Name the account with letters, digits or _, e.g. personal." }, { status: 400 });
  }
  if (typeof address !== "string" || !isAddress(address)) {
    return Response.json({ error: "That isn't an email address." }, { status: 400 });
  }
  // "--" so nothing in them is taken for an option.
  const job = await startJob("gmail", ["auth", "gmail", "--", name, address], address);
  if (!job) return Response.json({ error: "A sign-in is already waiting in the browser." }, { status: 409 });
  return Response.json({ job }, { status: 202, headers: NO_STORE });
}
