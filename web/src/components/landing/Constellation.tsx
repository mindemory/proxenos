"use client";

import { useEffect, useRef } from "react";

import type { SummaryResponse } from "@/lib/types";

type Shape = SummaryResponse["constellation"];

const TURN_SECONDS = 1200; // one slow revolution every twenty minutes
const SWAY_PX = 3.5; // how far each point wanders from its place

/**
 * The network's core drawn as a night sky behind the landing: people as points, ties as faint
 * lines, the whole field turning slowly and each point swaying a little. Positions only; the
 * picture carries no names. With reduced motion it is drawn once and stays still.
 */
export function Constellation({ shape }: { shape: Shape | null }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx || !shape || shape.nodes.length === 0) return;

    const still = window.matchMedia("(prefers-reduced-motion: reduce)");
    const nodes = shape.nodes;
    const edges = shape.edges.filter(([a, b]) => nodes[a] && nodes[b]);
    // Each point's own sway: a phase and a speed from its index, so the motion never syncs up.
    const phase = nodes.map((_, i) => (i * 2.399963) % (Math.PI * 2));
    const speed = nodes.map((_, i) => 0.18 + ((i * 37) % 23) / 100);
    const pos = new Float32Array(nodes.length * 2);
    let width = 0;
    let height = 0;
    let frame = 0;
    let pointer = { x: 0, y: 0 };
    let eased = { x: 0, y: 0 };
    const started = performance.now();

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = canvas.clientWidth;
      height = canvas.clientHeight;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const draw = (seconds: number, moving: boolean) => {
      ctx.clearRect(0, 0, width, height);
      const scale = Math.max(width, height) * 1.08;
      const angle = moving ? (seconds / TURN_SECONDS) * Math.PI * 2 : 0;
      const cos = Math.cos(angle);
      const sin = Math.sin(angle);
      eased = moving
        ? { x: eased.x + (pointer.x - eased.x) * 0.04, y: eased.y + (pointer.y - eased.y) * 0.04 }
        : { x: 0, y: 0 };
      const cx = width / 2 - eased.x * 14;
      const cy = height / 2 - eased.y * 14;
      for (let i = 0; i < nodes.length; i++) {
        const ux = (nodes[i][0] - 0.5) * scale;
        const uy = (nodes[i][1] - 0.5) * scale;
        const sway = moving ? SWAY_PX : 0;
        pos[i * 2] = cx + ux * cos - uy * sin + Math.sin(seconds * speed[i] + phase[i]) * sway;
        pos[i * 2 + 1] = cy + ux * sin + uy * cos + Math.cos(seconds * speed[i] * 0.8 + phase[i]) * sway;
      }

      ctx.lineWidth = 1;
      ctx.strokeStyle = "rgba(163, 177, 255, 0.15)";
      ctx.beginPath();
      for (const [a, b] of edges) {
        ctx.moveTo(pos[a * 2], pos[a * 2 + 1]);
        ctx.lineTo(pos[b * 2], pos[b * 2 + 1]);
      }
      ctx.stroke();

      for (let i = 0; i < nodes.length; i++) {
        const size = nodes[i][2];
        const x = pos[i * 2];
        const y = pos[i * 2 + 1];
        const twinkle = moving ? 0.85 + 0.15 * Math.sin(seconds * (0.6 + speed[i]) + phase[i] * 3) : 1;
        if (size > 0.7) {
          // The busiest ties get a soft halo.
          const glow = ctx.createRadialGradient(x, y, 0, x, y, 10 + size * 8);
          glow.addColorStop(0, `rgba(163, 177, 255, ${0.22 * twinkle})`);
          glow.addColorStop(1, "rgba(163, 177, 255, 0)");
          ctx.fillStyle = glow;
          ctx.beginPath();
          ctx.arc(x, y, 10 + size * 8, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.fillStyle = `rgba(236, 233, 227, ${(0.3 + 0.55 * size) * twinkle})`;
        ctx.beginPath();
        ctx.arc(x, y, 0.8 + size * 2, 0, Math.PI * 2);
        ctx.fill();
      }
    };

    const loop = (t: number) => {
      draw((t - started) / 1000, true);
      frame = requestAnimationFrame(loop);
    };

    const start = () => {
      cancelAnimationFrame(frame);
      if (still.matches) draw(0, false);
      else frame = requestAnimationFrame(loop);
    };

    const onResize = () => {
      resize();
      if (still.matches) draw(0, false);
    };
    const onPointer = (e: PointerEvent) => {
      pointer = { x: e.clientX / Math.max(width, 1) - 0.5, y: e.clientY / Math.max(height, 1) - 0.5 };
    };

    resize();
    start();
    canvas.dataset.ready = "true";
    window.addEventListener("resize", onResize);
    window.addEventListener("pointermove", onPointer, { passive: true });
    still.addEventListener("change", start);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("pointermove", onPointer);
      still.removeEventListener("change", start);
    };
  }, [shape]);

  return (
    <canvas
      ref={ref}
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 h-full w-full opacity-0 transition-opacity duration-[1600ms] data-[ready=true]:opacity-100 motion-reduce:transition-none"
    />
  );
}
