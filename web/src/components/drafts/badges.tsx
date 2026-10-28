import { Ban, FileText, ListChecks, Mail, Map, Reply, Send, type LucideIcon } from "lucide-react";

import { SOURCES, SourceBadge } from "@/components/SourceBadge";
import { channelLabel, kindLabel } from "@/lib/drafts";
import { cn } from "@/lib/utils";

const KIND_ICON: Record<string, LucideIcon> = {
  reply: Reply,
  email: Mail,
  doc: FileText,
  plan: Map,
  checklist: ListChecks,
  blocked: Ban,
};

const BADGE = "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs whitespace-nowrap";

/** What the draft is: a reply, an email, a doc, a plan, a checklist, or a note on what's blocking. */
export function KindBadge({ kind }: { kind: string }) {
  const Icon = KIND_ICON[kind] ?? FileText;
  const blocked = kind === "blocked";
  return (
    <span
      className={cn(BADGE, blocked ? "bg-warn-bg text-warn-ink border border-warn-line" : "bg-accent/10 text-accent border border-accent/25")}
    >
      <Icon size={12} />
      {kindLabel(kind)}
    </span>
  );
}

/** Where it would be sent from, for the reader to do: mail, WhatsApp, Slack, in person. */
export function ChannelBadge({ channel }: { channel: string }) {
  const label = channelLabel(channel);
  if (!label) return null;
  if (SOURCES[channel]) return <SourceBadge kind={channel} label={label} />;
  return (
    <span className={cn(BADGE, "border border-line-strong bg-surface-2 text-ink/90")}>
      <Send size={12} />
      {label}
    </span>
  );
}
