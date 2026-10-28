import { Bookmark, Compass, FileText, Hash, MessageSquare, Newspaper, ThumbsDown, ThumbsUp, type LucideIcon } from "lucide-react";

import { ActionButton, type ActionTone } from "@/components/ActionButton";
import { authorLine, formatDate, percent, sourceLabel } from "@/lib/format";
import type { FeedItem, Kind, Reaction } from "@/lib/types";
import { cn } from "@/lib/utils";

const KIND_ICON: Record<Kind, LucideIcon> = {
  paper: FileText,
  news: Newspaper,
  post: MessageSquare,
};

const ACTIONS: { reaction: Reaction; label: string; icon: LucideIcon; tone: ActionTone }[] = [
  { reaction: "useful", label: "Useful", icon: ThumbsUp, tone: "ok" },
  { reaction: "not_me", label: "Not me", icon: ThumbsDown, tone: "bad" },
  { reaction: "save", label: "Save", icon: Bookmark, tone: "accent" },
];

interface ItemCardProps {
  item: FeedItem;
  flash?: boolean;
  onReact: (item: FeedItem, reaction: Reaction) => void;
  onOpen: (item: FeedItem) => void;
}

export function TitleLink({ item, onOpen }: { item: FeedItem; onOpen: (item: FeedItem) => void }) {
  if (!item.url) return <>{item.title}</>;
  return (
    <a
      href={item.url}
      target="_blank"
      rel="noopener noreferrer"
      onClick={() => onOpen(item)}
      onAuxClick={(e) => e.button === 1 && onOpen(item)}
      className="rounded hover:underline decoration-accent/60 underline-offset-4"
    >
      {item.title}
    </a>
  );
}

export function ItemCard({ item, flash = false, onReact, onOpen }: ItemCardProps) {
  const Icon = KIND_ICON[item.kind];
  const saved = item.reaction === "save";
  const authors = authorLine(item.authors);
  const published = formatDate(item.published);
  const isPaper = item.kind === "paper";

  return (
    <article
      className={cn(
        "px-4 sm:px-6 py-5 transition-opacity",
        flash && "row-flash",
        item.reaction === "not_me" && "opacity-55 hover:opacity-85",
      )}
    >
      <div className="flex gap-3 sm:gap-4">
        <div className="w-9 h-9 rounded-full flex-shrink-0 bg-surface-2 text-muted flex items-center justify-center">
          <Icon size={17} strokeWidth={2} />
        </div>

        <div className="flex-1 min-w-0 space-y-3">
          {/* Source, kind, date, match */}
          <div className="flex justify-between items-start gap-3 pt-1.5">
            <div className="flex items-center gap-x-2 gap-y-1 flex-wrap min-w-0 text-sm">
              <span className="font-medium text-ink truncate">{sourceLabel(item.source)}</span>
              <span className="eyebrow">{item.kind}</span>
              {published && <span className="num text-xs text-muted">{published}</span>}
              {item.opened && <span className="text-xs text-muted">· opened</span>}
            </div>
            <span
              className="num text-xs text-accent bg-accent/10 border border-accent/25 px-2 py-0.5 rounded-full whitespace-nowrap"
              title="Match with your profile"
            >
              {percent(item.score)}%
            </span>
          </div>

          {/* Why it matters to the user */}
          {item.why && <p className="text-[15px] text-ink leading-relaxed">{item.why}</p>}

          {(item.interest || item.explore) && (
            <div className="flex flex-wrap gap-2">
              {item.interest && (
                <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs bg-surface-2 text-muted max-w-full">
                  <Hash className="w-3 h-3 mr-1 flex-shrink-0" />
                  <span className="truncate">{item.interest}</span>
                </span>
              )}
              {item.explore && (
                <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs border border-accent/25 text-accent">
                  <Compass className="w-3 h-3 mr-1" />
                  Explore
                </span>
              )}
            </div>
          )}

          {/* Papers get the citation card; news and posts a plain card. */}
          <div
            className={cn(
              "p-4 rounded-xl border relative",
              isPaper ? "bg-accent/[0.06] border-accent/25" : "bg-surface border-line",
            )}
          >
            {saved && (
              <div className="absolute top-3 right-3 bg-accent text-accent-ink text-xs font-medium px-2 py-0.5 rounded-full flex items-center gap-1">
                <Bookmark size={11} fill="currentColor" />
                Saved
              </div>
            )}
            <h3 className={cn("font-display text-ink leading-snug break-words", isPaper ? "text-xl" : "text-lg", saved && "pr-20")}>
              <TitleLink item={item} onOpen={onOpen} />
            </h3>
            {authors && (
              <div className="text-sm text-muted truncate mt-1" title={item.authors?.join(", ")}>
                {authors}
              </div>
            )}
            {item.summary && (
              <p className="text-sm text-muted leading-relaxed line-clamp-3 mt-2 break-words">{item.summary}</p>
            )}
          </div>

          {/* Reactions */}
          <div className="flex flex-wrap gap-2 pt-0.5">
            {ACTIONS.map((a) => (
              <ActionButton
                key={a.reaction}
                icon={a.icon}
                label={a.label}
                tone={a.tone}
                active={item.reaction === a.reaction}
                fillWhenActive={a.reaction === "save"}
                onClick={() => onReact(item, a.reaction)}
              />
            ))}
          </div>
        </div>
      </div>
    </article>
  );
}
