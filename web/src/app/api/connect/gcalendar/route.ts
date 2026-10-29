import { startSignIn } from "@/lib/connect";

export const dynamic = "force-dynamic";

/**
 * POST /api/connect/gcalendar {name, address} starts `proxenos auth gcalendar NAME ADDRESS`, which
 * opens Google's consent page for read-only calendar access and saves the token where Proxenos
 * keeps secrets. Answers at once; the page follows the sign-in through /api/connect/jobs.
 */
export async function POST(req: Request) {
  return startSignIn(req, "gcalendar");
}
