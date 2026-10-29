import { startSignIn } from "@/lib/connect";

export const dynamic = "force-dynamic";

/**
 * POST /api/connect/gmail {name, address} starts `proxenos auth gmail NAME ADDRESS`, which opens
 * Google's consent page in the browser and saves the token to .env. Answers at once; the page
 * follows the sign-in through /api/connect/jobs.
 */
export async function POST(req: Request) {
  return startSignIn(req, "gmail");
}
