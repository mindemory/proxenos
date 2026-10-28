// Memory results show sources the same way as everywhere else: one registry in SourceBadge.

import { SourceBadge, SourceIcon, sourceMeta, type SourceIconComponent } from "@/components/SourceBadge";

export function memorySourceLabel(source: string): string {
  return sourceMeta(source).label;
}

/** The icon component for a source, for places that pass one on (the command box). */
export function memorySourceIcon(source: string): SourceIconComponent {
  return sourceMeta(source).icon;
}

export function MemorySourceIcon({ source, size = 12 }: { source: string; size?: number }) {
  return <SourceIcon kind={source} size={size} />;
}

export function MemorySourceBadge({ source }: { source: string }) {
  return <SourceBadge kind={source} />;
}
