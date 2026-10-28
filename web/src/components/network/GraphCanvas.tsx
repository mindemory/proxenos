"use client";

import { useEffect, useImperativeHandle, useRef, type Ref } from "react";

import { GraphEngine, type ColourBy, type HoverInfo } from "@/lib/graphEngine";
import type { Filters, GraphModel } from "@/lib/graph";

export interface GraphHandle {
  focus: (idx: number, inset?: { right?: number; bottom?: number }) => void;
  fit: () => void;
  zoomBy: (factor: number) => void;
}

interface GraphCanvasProps {
  ref?: Ref<GraphHandle>;
  model: GraphModel;
  filters: Filters;
  selected: number | null;
  highlight: ReadonlySet<number> | null;
  colourBy: ColourBy;
  /** Pixels at the right and bottom covered by a panel, so fit and focus centre in what's left. */
  insetRight: number;
  insetBottom: number;
  label: string;
  onSelect: (idx: number | null) => void;
  onHover: (hover: HoverInfo | null) => void;
}

/** The interactive graph. It fills its parent, which must be positioned and have a size. */
export function GraphCanvas({
  ref,
  model,
  filters,
  selected,
  highlight,
  colourBy,
  insetRight,
  insetBottom,
  label,
  onSelect,
  onHover,
}: GraphCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engine = useRef<GraphEngine | null>(null);
  const callbacks = useRef({ onSelect, onHover });
  const colouring = useRef(colourBy);

  useEffect(() => {
    callbacks.current = { onSelect, onHover };
    colouring.current = colourBy;
  });

  // One engine per model. The effects below run after it exists, in this order.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const e = new GraphEngine(canvas, model, {
      interactive: true,
      colourBy: colouring.current,
      onSelect: (idx) => callbacks.current.onSelect(idx),
      onHover: (h) => callbacks.current.onHover(h),
    });
    engine.current = e;
    return () => {
      e.dispose();
      engine.current = null;
    };
  }, [model]);

  useEffect(() => {
    engine.current?.setInset({ right: insetRight, bottom: insetBottom });
  }, [model, insetRight, insetBottom]);
  useEffect(() => {
    engine.current?.setFilters(filters);
  }, [model, filters]);
  useEffect(() => {
    engine.current?.setSelection(selected);
  }, [model, selected]);
  useEffect(() => {
    engine.current?.setHighlight(highlight);
  }, [model, highlight]);
  useEffect(() => {
    engine.current?.setColourBy(colourBy);
  }, [model, colourBy]);

  useImperativeHandle(
    ref,
    () => ({
      focus: (idx, inset) => engine.current?.focus(idx, inset),
      fit: () => engine.current?.fitAll(),
      zoomBy: (factor) => engine.current?.zoomBy(factor),
    }),
    [],
  );

  return (
    <div className="absolute inset-0 overflow-hidden">
      <canvas ref={canvasRef} role="img" aria-label={label} className="block touch-none select-none" />
    </div>
  );
}
