import {
  Activity,
  AtSign,
  Briefcase,
  Camera,
  CalendarDays,
  Cloud,
  Database,
  FileText,
  Film,
  Globe,
  Hash,
  Images,
  ListTodo,
  Mail,
  Megaphone,
  MessageCircle,
  Music,
  NotebookText,
  Play,
  StickyNote,
  Users,
  type LucideIcon,
} from "lucide-react";

/** How each raw source looks in memory results: a name and a neutral icon (no brand marks). */
const SOURCES: Record<string, { label: string; icon: LucideIcon }> = {
  whatsapp: { label: "WhatsApp", icon: MessageCircle },
  slack: { label: "Slack", icon: Hash },
  email: { label: "Email", icon: Mail },
  calendar: { label: "Calendar", icon: CalendarDays },
  chrome: { label: "Browsing", icon: Globe },
  youtube: { label: "YouTube", icon: Play },
  photos: { label: "Photos", icon: Images },
  linkedin: { label: "LinkedIn", icon: Briefcase },
  facebook: { label: "Facebook", icon: Users },
  instagram: { label: "Instagram", icon: Camera },
  twitter: { label: "Twitter", icon: AtSign },
  threads: { label: "Threads", icon: AtSign },
  bluesky: { label: "Bluesky", icon: Cloud },
  notes: { label: "Notes", icon: NotebookText },
  keep: { label: "Keep", icon: StickyNote },
  gtasks: { label: "Tasks", icon: ListTodo },
  drive: { label: "Drive", icon: FileText },
  letterboxd: { label: "Letterboxd", icon: Film },
  spotify: { label: "Spotify", icon: Music },
  strava: { label: "Strava", icon: Activity },
  mentions: { label: "Mentions", icon: Megaphone },
  website: { label: "Website", icon: Globe },
};

export function memorySourceLabel(source: string): string {
  return SOURCES[source]?.label ?? source.charAt(0).toUpperCase() + source.slice(1);
}

/** The icon component for a source, for places that pass one on (the command box). */
export function memorySourceIcon(source: string): LucideIcon {
  return SOURCES[source]?.icon ?? Database;
}

export function MemorySourceIcon({ source, size = 12 }: { source: string; size?: number }) {
  const Icon = SOURCES[source]?.icon ?? Database;
  return <Icon size={size} aria-hidden="true" />;
}

export function MemorySourceBadge({ source }: { source: string }) {
  return (
    <span className="inline-flex flex-shrink-0 items-center gap-1 whitespace-nowrap rounded-md bg-surface-2 px-1.5 py-0.5 text-xs text-ink/85">
      <MemorySourceIcon source={source} />
      {memorySourceLabel(source)}
    </span>
  );
}
