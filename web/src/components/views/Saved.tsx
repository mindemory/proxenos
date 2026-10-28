"use client";

import { Bookmark } from "lucide-react";

import { EmptyState, ErrorBanner, LoadingRows, NoVault } from "@/components/EmptyState";
import { ItemCard } from "@/components/feed/ItemCard";
import { useItems } from "@/lib/client";

export function Saved() {
  const { data, error, flashId, react, open, clearError } = useItems("/api/items?view=saved");

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load saved items: ${error}`} /> : <LoadingRows />;
  }

  if (!data.vault.exists) return <NoVault path={data.vault.path} />;

  if (data.items.length === 0) {
    return (
      <EmptyState icon={Bookmark} title="Nothing saved yet" command="twin clone tracker">
        Press Save on any feed item to keep it here. The feed itself comes from the tracker.
      </EmptyState>
    );
  }

  return (
    <div className="pb-24 md:pb-20">
      {error && <ErrorBanner message={error} onDismiss={clearError} />}
      <div className="px-4 sm:px-6 py-2 border-b border-line bg-surface/60 flex justify-between gap-2">
        <span className="eyebrow">Saved · most recent first</span>
        <span className="num text-xs text-muted">{data.items.length}</span>
      </div>
      <div className="divide-y divide-line border-b border-line">
        {data.items.map((it) => (
          <ItemCard key={it.id} item={it} flash={flashId === it.id} onReact={react} onOpen={open} />
        ))}
      </div>
    </div>
  );
}
