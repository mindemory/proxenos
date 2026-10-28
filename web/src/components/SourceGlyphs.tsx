import type { SVGProps } from "react";

// Outline glyphs in the same grid and stroke as lucide (24 units, 2-unit round strokes), for the
// sources lucide has no fitting shape for. Each one echoes the service's own mark in a few
// strokes, so it reads at 12 to 16 pixels in the source's colour.

export type GlyphProps = Omit<SVGProps<SVGSVGElement>, "ref"> & { size?: number | string };

function Glyph({ size = 24, children, ...rest }: GlyphProps & { children: React.ReactNode }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

/** X (Twitter): the crossed strokes, one of them a band. */
export function XGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <path d="M4 4h4.2L20 20h-4.2Z" />
      <path d="M19.5 4 13.4 10.6M4.5 20l6.1-6.6" />
    </Glyph>
  );
}

/** Bluesky: a butterfly. */
export function ButterflyGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <path d="M12 10.8C10.4 7.6 6.8 4 4.4 4 2.8 4 2.6 5.6 2.6 7c0 1.6.8 4.6 4.4 5-3.2.6-3.8 2.8-2 4.6 2.6 2.6 4.6-.4 7-4.6 2.4 4.2 4.4 7.2 7 4.6 1.8-1.8 1.2-4-2-4.6 3.6-.4 4.4-3.4 4.4-5 0-1.4-.2-3-1.8-3-2.4 0-6 3.6-7.6 6.8Z" />
    </Glyph>
  );
}

/** Letterboxd: three overlapping circles in a row. */
export function ThreeDotsGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <circle cx="5.5" cy="12" r="3.5" />
      <circle cx="12" cy="12" r="3.5" />
      <circle cx="18.5" cy="12" r="3.5" />
    </Glyph>
  );
}

/** Spotify: a disc with three arcs. */
export function SoundArcsGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <circle cx="12" cy="12" r="10" />
      <path d="M7 9.6c3.3-1 7.1-.7 10 1.1M7.7 12.8c2.7-.7 5.6-.4 7.9.9M8.4 15.8c2-.5 4.1-.3 5.8.7" />
    </Glyph>
  );
}

/** Strava: a tall peak and a small one below it, upside down. */
export function PeaksGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <path d="M3.5 14 10 2.5 16.5 14" />
      <path d="m12.5 15.5 3 6 3-6" />
    </Glyph>
  );
}

/** YouTube: a rounded screen with a play mark. */
export function PlayScreenGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <rect x="2" y="5" width="20" height="14" rx="4.5" />
      <path d="m10 9.2 4.8 2.8-4.8 2.8Z" />
    </Glyph>
  );
}

/** Chrome (browsing history): a lens with three blades. */
export function ApertureGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <circle cx="12" cy="12" r="10" />
      <circle cx="12" cy="12" r="3.8" />
      <path d="M21.2 8H12M3.9 6.1l4.8 7.8M10.6 21.9l4.7-7.9" />
    </Glyph>
  );
}

/** LinkedIn: a rounded square with "in". */
export function InSquareGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <rect x="3" y="3" width="18" height="18" rx="3.5" />
      <path d="M8 10.5V16M8 7.6v.01M11.5 16v-5.5M11.5 13a2.5 2.5 0 0 1 5 0v3" />
    </Glyph>
  );
}

/** Facebook: an "f" in a circle. */
export function FCircleGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <circle cx="12" cy="12" r="10" />
      <path d="M15.5 7.5h-1.6A2.4 2.4 0 0 0 11.5 10v12M9 13h5.5" />
    </Glyph>
  );
}

/** Instagram: a rounded square, a lens and a dot. */
export function CameraSquareGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <rect x="3" y="3" width="18" height="18" rx="5.5" />
      <circle cx="12" cy="12" r="4" />
      <path d="M17.3 6.7h.01" />
    </Glyph>
  );
}

/** Google Drive: the triangle made of three bands. */
export function TriangleBandsGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <path d="M8.6 3.5h6.8L22 15l-3.4 5.5H5.4L2 15Z" />
      <path d="M8.6 3.5 15.2 15H2M15.4 3.5 8.8 15l-3.4 5.5M15.2 15l3.4 5.5" />
    </Glyph>
  );
}
