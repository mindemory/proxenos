import { startJob } from "@/lib/connect";
import { NO_STORE, readLocalJson } from "@/lib/guard";

export const dynamic = "force-dynamic";

/**
 * POST /api/connect/whatsapp {} starts `proxenos ingest whatsapp`, which reads the Mac app's local
 * store into the vault. Answers at once; the page follows the read through /api/connect/jobs.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const job = await startJob("whatsapp", ["ingest", "whatsapp"]);
  if (!job) return Response.json({ error: "WhatsApp is already being read." }, { status: 409 });
  return Response.json({ job }, { status: 202, headers: NO_STORE });
}
