"use client";

import { create } from "qrcode";
import { useMemo } from "react";

/** The blank border, in squares, that a phone's camera needs to find the code. */
const QUIET = 4;

/** A QR code of `value` as an SVG: dark squares on white, drawn here so nothing is sent anywhere. */
export function QrCode({ value }: { value: string }) {
  const drawn = useMemo(() => {
    try {
      const modules = create(value, { errorCorrectionLevel: "M" }).modules;
      const size = modules.size;
      const dark = (row: number, col: number) => modules.get(row, col) === 1;
      // One rectangle per run of dark squares in a row, as a single path.
      let path = "";
      for (let row = 0; row < size; row++) {
        for (let col = 0; col < size; col++) {
          if (!dark(row, col)) continue;
          let run = 1;
          while (col + run < size && dark(row, col + run)) run++;
          path += `M${col + QUIET} ${row + QUIET}h${run}v1h-${run}z`;
          col += run;
        }
      }
      return { side: size + QUIET * 2, path };
    } catch {
      // Too long to encode: the link beside it still works.
      return null;
    }
  }, [value]);

  if (!drawn) return null;
  return (
    <svg
      viewBox={`0 0 ${drawn.side} ${drawn.side}`}
      role="img"
      aria-label="QR code for the address"
      shapeRendering="crispEdges"
      className="h-44 w-44 flex-shrink-0 rounded-xl bg-white text-black"
    >
      <path d={drawn.path} fill="currentColor" />
    </svg>
  );
}
