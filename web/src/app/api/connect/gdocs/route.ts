import { startSignIn } from "@/lib/connect";

export const dynamic = "force-dynamic";

/**
 * POST /api/connect/gdocs {name, address} starts `proxenos auth gdocs NAME ADDRESS`, which opens
 * Google's consent page for access to only the files Proxenos makes in the Drive (a project's
 * manuscript as a Google Doc) and saves the token where Proxenos keeps secrets. Answers at once;
 * the page follows the sign-in through /api/connect/jobs.
 */
export async function POST(req: Request) {
  return startSignIn(req, "gdocs");
}
