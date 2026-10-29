import { startSignIn } from "@/lib/connect";

export const dynamic = "force-dynamic";

/**
 * POST /api/connect/microsoft {name, address} starts `proxenos auth microsoft NAME ADDRESS`, which
 * opens Microsoft's sign-in in the browser and saves the token where Proxenos keeps secrets.
 * Answers at once; the page follows the sign-in through /api/connect/jobs.
 */
export async function POST(req: Request) {
  return startSignIn(req, "microsoft");
}
