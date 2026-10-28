"use client";

import { useId, useRef, useState } from "react";

import { shortDate } from "@/lib/format";

interface SparklineProps {
  values: number[];
  /** One YYYY-MM-DD per value, oldest first. */
  days: string[];
  /** The line's colour: a source's accent. */
  color: string;
  /** What a value counts, for the tooltip ("records"). */
  unit?: string;
  height?: number;
  /** Shared top of the scale, so rows can be compared; each row's own peak when absent. */
  max?: number;
  label: string;
}

const W = 300; // viewBox width; the svg stretches to its box and the stroke stays 2px

/**
 * A 30-day line with a soft area under it, the latest day marked, and a crosshair with the
 * day's value under the pointer. Hand-drawn SVG, no chart library.
 */
export function Sparkline({ values, days, color, unit = "records", height = 36, max, label }: SparklineProps) {
  const gradient = useId();
  const box = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const n = values.length;
  if (n === 0) return null;

  const top = Math.max(max ?? 0, ...values, 1);
  const pad = 3; // keeps the 2px line and the end dot inside the box
  const x = (i: number) => (n === 1 ? W / 2 : (i / (n - 1)) * W);
  const y = (v: number) => pad + (1 - v / top) * (height - pad * 2);
  const line = values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(2)},${y(v).toFixed(2)}`).join("");
  const area = `${line}L${W},${height}L0,${height}Z`;
  const last = n - 1;
  const shown = hover ?? null;

  const pick = (clientX: number) => {
    const rect = box.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return;
    const i = Math.round(((clientX - rect.left) / rect.width) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };

  return (
    <div className="relative w-full" style={{ height }}>
      <svg
        ref={box}
        viewBox={`0 0 ${W} ${height}`}
        preserveAspectRatio="none"
        className="block h-full w-full overflow-visible"
        role="img"
        aria-label={label}
        onPointerMove={(e) => pick(e.clientX)}
        onPointerLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id={gradient} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.28" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        <line x1="0" x2={W} y1={height - 0.5} y2={height - 0.5} stroke="var(--c-line)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        <path d={area} fill={`url(#${gradient})`} />
        <path
          d={line}
          fill="none"
          stroke={color}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
        {shown !== null && (
          <line
            x1={x(shown)}
            x2={x(shown)}
            y1="0"
            y2={height}
            stroke="var(--c-muted)"
            strokeOpacity="0.5"
            strokeWidth="1"
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>
      {/* Dots are HTML so they stay round while the svg stretches. */}
      <Dot left={(x(shown ?? last) / W) * 100} top={y(values[shown ?? last])} color={color} ring={shown === null} />
      {shown !== null && (
        <div
          role="presentation"
          className="pointer-events-none absolute -top-8 z-10 -translate-x-1/2 whitespace-nowrap rounded-md border border-line-strong bg-surface-2 px-2 py-0.5 text-xs text-ink shadow-pop"
          style={{ left: `${Math.min(88, Math.max(12, (x(shown) / W) * 100))}%` }}
        >
          <span className="num">{values[shown].toLocaleString()}</span> {unit}
          <span className="text-muted"> · {shortDate(days[shown])}</span>
        </div>
      )}
    </div>
  );
}

function Dot({ left, top, color, ring }: { left: number; top: number; color: string; ring: boolean }) {
  return (
    <span
      aria-hidden="true"
      className="pointer-events-none absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full"
      style={{
        left: `${left}%`,
        top,
        background: color,
        boxShadow: ring ? "0 0 0 2px var(--c-surface)" : `0 0 0 2px var(--c-surface), 0 0 0 4px color-mix(in oklab, ${color} 35%, transparent)`,
      }}
    />
  );
}
