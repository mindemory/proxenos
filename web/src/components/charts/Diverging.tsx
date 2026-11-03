"use client";

import { useEffect, useRef, useState } from "react";

interface DivergingProps {
  /** One value a period, from -max to max; null where there's none. */
  values: (number | null)[];
  /** What the chart shows, for a screen reader: "Mood of your writing, by day". */
  label: string;
  picked: number | null;
  onHover: (i: number | null) => void;
  onPick: (i: number) => void;
  /** A value as the slider says it: "brighter (0.42)". */
  format: (v: number | null) => string;
  /** A period's name, for a screen reader: "March 4". */
  name: (i: number) => string;
  max?: number;
  height?: number;
}

const GAP = 2;
const MAX_BAR = 24;
const RADIUS = 3;

/** A column from the middle line up (above zero) or down (below), rounded at its far end. */
function column(x: number, w: number, mid: number, h: number): string {
  const r = Math.min(RADIUS, w / 2, Math.abs(h));
  if (h >= 0) {
    const top = mid - h;
    return `M${x},${mid}V${top + r}Q${x},${top} ${x + r},${top}H${x + w - r}Q${x + w},${top} ${x + w},${top + r}V${mid}Z`;
  }
  const bottom = mid - h;
  return `M${x},${mid}V${bottom - r}Q${x},${bottom} ${x + r},${bottom}H${x + w - r}Q${x + w},${bottom} ${x + w},${bottom - r}V${mid}Z`;
}

/**
 * Values either side of zero over time, such as how bright or heavy each day's writing ran: up in
 * the good colour, down in the warning one, so the side says it as well as the colour. A period
 * with no value is a dot on the line. As the Columns charts are, it's a slider to a screen reader,
 * the arrow keys move along, and the period picked or under the pointer is drawn at full strength.
 */
export function Diverging({ values, label, picked, onHover, onPick, format, name, max = 1, height = 72 }: DivergingProps) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    setWidth(el.getBoundingClientRect().width);
    const seen = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    seen.observe(el);
    return () => seen.disconnect();
  }, []);

  const n = values.length;
  const slot = n ? width / n : 0;
  const bar = Math.max(1, Math.min(MAX_BAR, slot >= GAP + 2 ? slot - GAP : slot));
  const mid = height / 2;
  const reach = mid - 2;
  const at = (clientX: number) => {
    const rect = box.current?.getBoundingClientRect();
    if (!rect || !n) return null;
    return Math.max(0, Math.min(n - 1, Math.floor(((clientX - rect.left) / rect.width) * n)));
  };
  const now = picked !== null && picked < n ? picked : n - 1;

  return (
    <div
      ref={box}
      role="slider"
      aria-label={label}
      aria-valuemin={1}
      aria-valuemax={Math.max(n, 1)}
      aria-valuenow={now + 1}
      aria-valuetext={n ? `${name(now)}: ${format(values[now])}` : "No data"}
      tabIndex={0}
      className="relative min-w-0 cursor-crosshair rounded-sm"
      style={{ height }}
      onPointerMove={(e) => onHover(at(e.clientX))}
      onPointerLeave={() => onHover(null)}
      onClick={(e) => {
        const i = at(e.clientX);
        if (i !== null) onPick(i);
      }}
      onKeyDown={(e) => {
        if (!n || (e.key !== "ArrowLeft" && e.key !== "ArrowRight" && e.key !== "Home" && e.key !== "End")) return;
        e.preventDefault();
        const from = picked ?? n - 1;
        const to = e.key === "Home" ? 0 : e.key === "End" ? n - 1 : from + (e.key === "ArrowLeft" ? -1 : 1);
        onPick(Math.max(0, Math.min(n - 1, to)));
      }}
    >
      {width > 0 && (
        <svg width={width} height={height} className="block overflow-visible" aria-hidden="true">
          {picked !== null && picked < n && (
            <rect x={picked * slot} y="0" width={slot} height={height} fill="var(--c-surface-2)" opacity="0.6" />
          )}
          <line x1="0" x2={width} y1={mid} y2={mid} stroke="var(--c-line-strong)" strokeWidth="1" />
          {values.map((v, i) => {
            const x = i * slot + (slot - bar) / 2;
            const strong = picked === null || picked === i ? 0.9 : 0.45;
            if (v === null) {
              return <circle key={i} cx={x + bar / 2} cy={mid} r={Math.min(2, bar / 2)} fill="var(--c-faint)" opacity={strong} />;
            }
            const h = Math.max(1, (Math.min(Math.abs(v), max) / max) * reach) * (v >= 0 ? 1 : -1);
            return <path key={i} d={column(x, bar, mid, h)} fill={v >= 0 ? "var(--c-ok-ink)" : "var(--c-warn-ink)"} opacity={strong} />;
          })}
        </svg>
      )}
    </div>
  );
}
