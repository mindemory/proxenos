import { draftOpen, openTarget, recipientAddress, recipientQueries } from "@/lib/actions";
import { isLive } from "@/lib/drafts";
import { NO_STORE, rejectNonLocal } from "@/lib/guard";
import { findAddresses } from "@/lib/recipients";
import type { DraftOpen, DraftsViewResponse } from "@/lib/types";
import { getDraftReviews, getDrafts, vaultPath } from "@/lib/vault";

export const dynamic = "force-dynamic";

/**
 * GET /api/drafts: every file in clones/drafts, newest first, with what each draft that is still
 * the reader's can open (a Gmail compose link, a chat picker, a download) and how reviews have
 * gone so far. Nothing is sent: an action only opens an app with the text in it.
 */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;

  const base = await getDrafts();
  const live = base.drafts.filter((d) => isLive(d.status));

  // Only an email needs the vault, to turn a name into an address.
  const mail = live.filter((d) => openTarget(d) === "gmail");
  const found = await findAddresses(vaultPath(), mail.flatMap((d) => recipientQueries(d.to))).catch(
    () => new Map<string, string>(),
  );
  const actions: Record<string, DraftOpen> = {};
  for (const d of live) actions[d.id] = draftOpen(d, recipientAddress(d.to, found));

  const body: DraftsViewResponse = { ...base, actions, record: await getDraftReviews() };
  return Response.json(body, { headers: NO_STORE });
}
