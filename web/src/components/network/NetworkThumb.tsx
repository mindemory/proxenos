"use client";

import { useEffect, useMemo, useRef } from "react";
import { Network as NetworkIcon } from "lucide-react";

import { QuietLine } from "@/components/EmptyState";
import { useJson } from "@/lib/client";
import { buildThumbGraph } from "@/lib/graph";
import { GraphEngine } from "@/lib/graphEngine";
import type { GraphThumb } from "@/lib/types";

/** A small picture of the network: the busiest connected people, settling into place. */
export function NetworkThumb({ onOpen }: { onOpen: () => void }) {
  const { data, error } = useJson<GraphThumb>("/api/network/graph");
  const model = useMemo(() => (data ? buildThumbGraph(data) : null), [data]);
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const el = canvas.current;
    if (!el || !model || model.nodes.length === 0) return;
    const engine = new GraphEngine(el, model, { interactive: false, warm: 12 });
    return () => engine.dispose();
  }, [model]);

  if (error) return <p className="text-sm text-muted">Couldn&apos;t load the graph.</p>;
  if (!data) return <div className="h-44 rounded-xl bg-bg animate-pulse" aria-busy="true" />;
  if (!data.exists) {
    return <QuietLine command="proxenos clone network --people-only">No people index yet:</QuietLine>;
  }

  return (
    <div className="space-y-3">
      <button
        onClick={onOpen}
        aria-label={`Open the network graph: ${data.connected} people connected, ${data.edges} ties`}
        className="relative block h-44 w-full overflow-hidden rounded-xl border border-line bg-bg transition-colors hover:border-accent/40"
      >
        {model && model.nodes.length > 0 ? (
          <div className="absolute inset-0">
            <canvas ref={canvas} aria-hidden="true" className="block" />
          </div>
        ) : (
          <span className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-4 text-center text-sm text-muted">
            <NetworkIcon size={20} />
            No ties yet. Run the people index again to add them.
          </span>
        )}
      </button>
      <p className="text-sm text-muted leading-relaxed">
        <span className="num text-ink">{data.people.toLocaleString()}</span> people,{" "}
        <span className="num text-ink">{data.edges.toLocaleString()}</span> ties in{" "}
        <span className="num text-ink">{data.groups.toLocaleString()}</span> shared contexts.
      </p>
    </div>
  );
}
