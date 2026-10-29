import { draftOpen, normName, openTarget, recipientAddress, recipientQueries } from "@/lib/actions";
import { isLive } from "@/lib/drafts";
import { findPhones } from "@/lib/phones";
import { findAddresses } from "@/lib/recipients";
import type { DraftOpen, DraftsViewResponse } from "@/lib/types";
import { getDraftCloseness, getDraftReviews, getDrafts, vaultPath } from "@/lib/vault";

/**
 * Every file in clones/drafts, newest first, with what each draft that is still the reader's can open
 * (a Gmail compose link, a chat picker, a download) and how reviews have gone so far. The first call
 * after the server starts looks through the vault for addresses and phones, which takes a while, so
 * the server makes it once at startup (src/instrumentation.ts) rather than on a reader's click.
 */
export async function draftsView(): Promise<DraftsViewResponse> {
  const base = await getDrafts();
  const live = base.drafts.filter((d) => isLive(d.status));

  const mail = live.filter((d) => openTarget(d) === "gmail");
  const found = await findAddresses(
    vaultPath(),
    mail.flatMap((d) => recipientQueries(d.to)),
  ).catch(() => new Map<string, string>());
  const chats = live.filter((d) => openTarget(d) === "whatsapp" && d.to);
  const phones = await findPhones(
    vaultPath(),
    chats.map((d) => d.to),
  ).catch(() => new Map<string, string>());
  const actions: Record<string, DraftOpen> = {};
  for (const d of live) {
    actions[d.id] = draftOpen(d, recipientAddress(d.to, found), phones.get(normName(d.to)) ?? "");
  }

  const [record, closeness] = await Promise.all([getDraftReviews(), getDraftCloseness()]);
  return { ...base, actions, record, closeness };
}
