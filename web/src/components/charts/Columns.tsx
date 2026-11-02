"use client";

import { useEffect, useRef, useState } from "react";

interface ColumnsProps {
  values: number[];
  /** What the chart shows, for a screen reader: "Hours listened, by week". */
  label: string;
  /** The period picked or under the pointer, shared by the charts stacked with this one. */
  picked: number | null;
  onHover: (i: number | null) => void;
  onPick: (i: number) => void;
  /** The top of the scale, shared by charts that compare; this chart's own peak when absent. */
  max?: number;
  /** The top tick's text: "12 h". */
  format: (v: number) => string;
  height?: number;
}

const GAP = 2; // the surface gap between neighbouring columns
const MAX_BAR = 24;
const RADIUS = 4;

/** A tick a little above the peak that reads cleanly: 1, 2, 2.5, 5 or 10 of a power of ten. */
export function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const step = [1, 2, 2.5, 5, 10].find((s) => s * p >= v) ?? 10;
  return step * p;
}

/** A column with a rounded top, square at the baseline. */
function column(x: number, w: number, base: number, h: number): string {
  const r = Math.min(RADIUS, w / 2, h);
  const top = base - h;
  return `M${x},${base}V${top + r}Q${x},${top} ${x + r},${top}H${x + w - r}Q${x + w},${top} ${x + w},${top + r}V${base}Z`;
}

/**
 * One series over time as thin columns in the accent, aligned with the charts stacked above and
 * below it: the same periods in the same places. The period picked or under the pointer is drawn
 * at full strength and the rest stepped back; the whole slot is the hit target, and the arrow
 * keys move along. Hand-drawn SVG, measured to its box so the rounded tops stay round.
 */
export function Columns({ values, label, picked, onHover, onPick, max, format, height = 56 }: ColumnsProps) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    setWidth(el.getBoundingClientRect().width); // drawn at once, not only when the box next changes
    const seen = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    seen.observe(el);
    return () => seen.disconnect();
  }, []);

  const n = values.length;
  const top = niceMax(Math.max(max ?? 0, ...values));
  const slot = n ? width / n : 0;
  const bar = Math.max(1, Math.min(MAX_BAR, slot >= GAP + 2 ? slot - GAP : slot));
  const base = height - 0.5;
  const at = (clientX: number) => {
    const rect = box.current?.getBoundingClientRect();
    if (!rect || !n) return null;
    return Math.max(0, Math.min(n - 1, Math.floor(((clientX - rect.left) / rect.width) * n)));
  };

  return (
    <div className="flex items-stretch gap-2">
      <div
        ref={box}
        role="img"
        aria-label={label}
        tabIndex={0}
        className="relative min-w-0 flex-1 cursor-crosshair rounded-sm"
        style={{ height }}
        onPointerMove={(e) => onHover(at(e.clientX))}
        onPointerLeave={() => onHover(null)}
        onClick={(e) => {
          const i = at(e.clientX);
          if (i !== null) onPick(i);
        }}
        onKeyDown={(e) => {
          if (!n || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
          e.preventDefault();
          const from = picked ?? n - 1;
          onPick(Math.max(0, Math.min(n - 1, from + (e.key === "ArrowLeft" ? -1 : 1))));
        }}
      >
        {width > 0 && (
          <svg width={width} height={height} className="block overflow-visible" aria-hidden="true">
            <line x1="0" x2={width} y1="0.5" y2="0.5" stroke="var(--c-line)" strokeWidth="1" />
            <line x1="0" x2={width} y1={base} y2={base} stroke="var(--c-line-strong)" strokeWidth="1" />
            {picked !== null && picked < n && (
              <rect x={picked * slot} y="0" width={slot} height={height} fill="var(--c-surface-2)" opacity="0.6" />
            )}
            {values.map((v, i) => {
              const h = (v / top) * (height - 2);
              if (h <= 0) return null;
              return (
                <path
                  key={i}
                  d={column(i * slot + (slot - bar) / 2, bar, base, Math.max(h, 1))}
                  fill="var(--c-accent)"
                  opacity={picked === null || picked === i ? 0.9 : 0.42}
                />
              );
            })}
          </svg>
        )}
      </div>
      <span className="num w-12 shrink-0 text-right text-[0.6875rem] leading-none text-faint">{format(top)}</span>
    </div>
  );
}
