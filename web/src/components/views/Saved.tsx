"use client";

import { Bookmark } from "lucide-react";

import { EmptyState, ErrorBanner, LoadingRows } from "@/components/EmptyState";
import { ItemCard } from "@/components/feed/ItemCard";
import { useItems } from "@/lib/client";

export function Saved() {
  const { data, error, react, open } = useItems("/api/items?view=saved");

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load saved items: ${error}`} /> : <LoadingRows />;
  }

  if (data.items.length === 0) {
    return (
      <EmptyState icon={Bookmark} title="Nothing saved yet" command="twin clone tracker">
        Press Save on any feed item to keep it here. The feed itself comes from the tracker.
      </EmptyState>
    );
  }

  return (
    <div className="pb-24 md:pb-20">
      {error && <ErrorBanner message={error} />}
      <div className="px-4 sm:px-6 py-2 border-b border-gray-100 bg-white/40 text-xs font-bold uppercase tracking-wider text-text-secondary">
        {data.items.length} saved · most recent first
      </div>
      <div className="divide-y divide-gray-100 border-b border-gray-100">
        {data.items.map((it) => (
          <ItemCard key={it.id} item={it} onReact={react} onOpen={open} />
        ))}
      </div>
    </div>
  );
}
