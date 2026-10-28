import {
  Activity,
  AtSign,
  Briefcase,
  CalendarDays,
  Camera,
  Cloud,
  Database,
  Globe,
  Hash,
  Mail,
  Megaphone,
  MessageCircle,
  Music,
  type LucideIcon,
} from "lucide-react";

import { sourceLabel } from "@/lib/format";

/** One neutral icon per raw source. Generic shapes, not brand marks. */
export const SOURCE_ICON: Record<string, LucideIcon> = {
  whatsapp: MessageCircle,
  spotify: Music,
  strava: Activity,
  email: Mail,
  slack: Hash,
  twitter: AtSign,
  linkedin: Briefcase,
  instagram: Camera,
  bluesky: Cloud,
  website: Globe,
  mentions: Megaphone,
  calendar: CalendarDays,
};

export function SourceIcon({ kind, size = 12 }: { kind: string; size?: number }) {
  const Icon = SOURCE_ICON[kind] ?? Database;
  return <Icon size={size} />;
}

export function SourceBadge({ kind }: { kind: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-surface-2 px-1.5 py-0.5 text-xs text-ink/85 whitespace-nowrap">
      <SourceIcon kind={kind} />
      {sourceLabel(kind)}
    </span>
  );
}
