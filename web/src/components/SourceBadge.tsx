import type { ComponentType, CSSProperties } from "react";
import {
  AtSign,
  CalendarDays,
  CircleCheck,
  Database,
  Globe,
  Images,
  Mail,
  Megaphone,
  MessageCircle,
  NotebookText,
  Hash,
  StickyNote,
} from "lucide-react";

import {
  ApertureGlyph,
  ButterflyGlyph,
  CameraSquareGlyph,
  FCircleGlyph,
  InSquareGlyph,
  PeaksGlyph,
  PlayScreenGlyph,
  SoundArcsGlyph,
  ThreeDotsGlyph,
  TriangleBandsGlyph,
  XGlyph,
} from "./SourceGlyphs";

export type SourceIconComponent = ComponentType<{
  size?: number | string;
  className?: string;
  strokeWidth?: number | string;
  "aria-hidden"?: boolean | "true" | "false";
}>;

export interface SourceMeta {
  label: string;
  icon: SourceIconComponent;
  /**
   * The source's accent, used for its icon and a faint tint behind it, never for text. Each
   * is a light step of the service's own hue, so it holds at least 6:1 on the cards.
   */
  color: string;
}

/** Every raw source: its name, an icon that echoes its mark, and its colour. One place, used everywhere. */
export const SOURCES: Record<string, SourceMeta> = {
  whatsapp: { label: "WhatsApp", icon: MessageCircle, color: "#5fd39b" },
  slack: { label: "Slack", icon: Hash, color: "#cf9cf2" },
  email: { label: "Email", icon: Mail, color: "#f29b84" },
  calendar: { label: "Calendar", icon: CalendarDays, color: "#8fb8fa" },
  chrome: { label: "Browsing", icon: ApertureGlyph, color: "#f2cb63" },
  youtube: { label: "YouTube", icon: PlayScreenGlyph, color: "#ff7b7b" },
  photos: { label: "Photos", icon: Images, color: "#f7b26a" },
  linkedin: { label: "LinkedIn", icon: InSquareGlyph, color: "#6fb1e8" },
  facebook: { label: "Facebook", icon: FCircleGlyph, color: "#8ea6f7" },
  instagram: { label: "Instagram", icon: CameraSquareGlyph, color: "#f17fbd" },
  twitter: { label: "X", icon: XGlyph, color: "#d9dce1" },
  threads: { label: "Threads", icon: AtSign, color: "#c9cdd3" },
  bluesky: { label: "Bluesky", icon: ButterflyGlyph, color: "#6ec6ff" },
  notes: { label: "Notes", icon: NotebookText, color: "#d8cba6" },
  keep: { label: "Keep", icon: StickyNote, color: "#f5d36a" },
  gtasks: { label: "Tasks", icon: CircleCheck, color: "#96b9f7" },
  drive: { label: "Drive", icon: TriangleBandsGlyph, color: "#a6d98a" },
  letterboxd: { label: "Letterboxd", icon: ThreeDotsGlyph, color: "#ffab73" },
  spotify: { label: "Spotify", icon: SoundArcsGlyph, color: "#7ee08a" },
  strava: { label: "Strava", icon: PeaksGlyph, color: "#ff9566" },
  mentions: { label: "Mentions", icon: Megaphone, color: "#e2aaf3" },
  website: { label: "Website", icon: Globe, color: "#a9b8cc" },
};

const UNKNOWN: Omit<SourceMeta, "label"> = { icon: Database, color: "#a3a9b4" };

export function sourceMeta(kind: string): SourceMeta {
  return SOURCES[kind] ?? { ...UNKNOWN, label: kind.charAt(0).toUpperCase() + kind.slice(1) };
}

/** Kept for places that pick an icon by name (draft channels). */
export const SOURCE_ICON: Record<string, SourceIconComponent> = Object.fromEntries(
  Object.entries(SOURCES).map(([k, v]) => [k, v.icon]),
);

/** The style that sets --src to a source's colour, for classes that use it. */
export function sourceStyle(kind: string): CSSProperties {
  return { "--src": sourceMeta(kind).color } as CSSProperties;
}

/** A source's icon, in its colour unless `plain`. */
export function SourceIcon({ kind, size = 12, plain = false }: { kind: string; size?: number; plain?: boolean }) {
  const { icon: Icon, color } = sourceMeta(kind);
  return (
    <span className="inline-flex flex-shrink-0" style={plain ? undefined : { color }} aria-hidden="true">
      <Icon size={size} strokeWidth={2} />
    </span>
  );
}

/** A source's icon on a soft disc of its colour, for rows and chart legends. */
export function SourceChip({ kind, size = 28 }: { kind: string; size?: number }) {
  return (
    <span
      style={sourceStyle(kind)}
      className="inline-flex flex-shrink-0 items-center justify-center rounded-lg border border-[color-mix(in_oklab,var(--src)_28%,transparent)] bg-[color-mix(in_oklab,var(--src)_12%,transparent)] text-[var(--src)]"
      aria-hidden="true"
    >
      <span className="flex items-center justify-center" style={{ width: size, height: size }}>
        <SourceIcon kind={kind} size={Math.round(size * 0.52)} plain />
      </span>
    </span>
  );
}

/** A source's name with its icon: a tinted pill whose text stays in the ink colour. */
export function SourceBadge({ kind, label }: { kind: string; label?: string }) {
  const meta = sourceMeta(kind);
  return (
    <span
      style={sourceStyle(kind)}
      className="inline-flex flex-shrink-0 items-center gap-1 whitespace-nowrap rounded-md border border-[color-mix(in_oklab,var(--src)_26%,transparent)] bg-[color-mix(in_oklab,var(--src)_10%,transparent)] px-1.5 py-0.5 text-xs text-ink/90"
    >
      <span className="text-[var(--src)]">
        <meta.icon size={12} strokeWidth={2.25} aria-hidden="true" />
      </span>
      {label ?? meta.label}
    </span>
  );
}
