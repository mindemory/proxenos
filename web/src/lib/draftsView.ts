import { draftOpen, normName, openTarget, recipientAddress, recipientQueries } from "@/lib/actions";
import { isLive } from "@/lib/drafts";
import { findPhones } from "@/lib/phones";
import { findAddresses } from "@/lib/recipients";
import type { DraftOpen, DraftsViewResponse } from "@/lib/types";
import { getDraftCloseness, getDraftReviews, getDrafts, vaultPath } from "@/lib/vault";

/**
 * Every file in clones/drafts, newest first, with what each draft that is still the reader's can open
 * (a Gmail compose link, a chat picker, a download) and how reviews have gone so far. Addresses and
 * phones come from the last look-up through the vault, at once; the server makes the first one as it
 * starts (src/instrumentation.ts), and a name never looked up waits at most a moment (recipients.ts).
 */
export async function draftsView(): Promise<DraftsViewResponse> {
  const base = await getDrafts();
  const live = base.drafts.filter((d) => isLive(d.status));

  const mail = live.filter((d) => openTarget(d) === "gmail");
  const chats = live.filter((d) => openTarget(d) === "whatsapp" && d.to);
  const [found, phones] = await Promise.all([
    findAddresses(
      vaultPath(),
      mail.flatMap((d) => recipientQueries(d.to)),
    ).catch(() => new Map<string, string>()),
    findPhones(
      vaultPath(),
      chats.map((d) => d.to),
    ).catch(() => new Map<string, string>()),
  ]);
  const actions: Record<string, DraftOpen> = {};
  for (const d of live) {
    actions[d.id] = draftOpen(d, recipientAddress(d.to, found), phones.get(normName(d.to)) ?? "");
  }

  const [record, closeness] = await Promise.all([getDraftReviews(), getDraftCloseness()]);
  return { ...base, actions, record, closeness };
}
