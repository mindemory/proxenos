import {
  Bookmark,
  Compass,
  FileText,
  Hash,
  MessageSquare,
  Newspaper,
  ThumbsDown,
  ThumbsUp,
  type LucideIcon,
} from "lucide-react";

import { authorLine, formatDate, percent, sourceLabel } from "@/lib/format";
import type { FeedItem, Kind, Reaction } from "@/lib/types";
import { cn } from "@/lib/utils";

const KIND_ICON: Record<Kind, LucideIcon> = {
  paper: FileText,
  news: Newspaper,
  post: MessageSquare,
};

const ACTIONS: {
  reaction: Reaction;
  label: string;
  icon: LucideIcon;
  idle: [text: string, circle: string];
  active: [text: string, circle: string];
}[] = [
  {
    reaction: "useful",
    label: "Useful",
    icon: ThumbsUp,
    idle: ["hover:text-green-600", "group-hover:bg-green-50"],
    active: ["text-green-600", "bg-green-50"],
  },
  {
    reaction: "not_me",
    label: "Not me",
    icon: ThumbsDown,
    idle: ["hover:text-red-600", "group-hover:bg-red-50"],
    active: ["text-red-600", "bg-red-50"],
  },
  {
    reaction: "save",
    label: "Save",
    icon: Bookmark,
    idle: ["hover:text-yellow-600", "group-hover:bg-yellow-50"],
    active: ["text-yellow-600", "bg-yellow-50"],
  },
];

interface ItemCardProps {
  item: FeedItem;
  onReact: (item: FeedItem, reaction: Reaction) => void;
  onOpen: (item: FeedItem) => void;
}

function TitleLink({ item, onOpen }: { item: FeedItem; onOpen: (item: FeedItem) => void }) {
  if (!item.url) return <>{item.title}</>;
  return (
    <a
      href={item.url}
      target="_blank"
      rel="noopener noreferrer"
      onClick={() => onOpen(item)}
      onAuxClick={(e) => e.button === 1 && onOpen(item)}
      className="focus:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
    >
      {item.title}
    </a>
  );
}

export function ItemCard({ item, onReact, onOpen }: ItemCardProps) {
  const Icon = KIND_ICON[item.kind];
  const saved = item.reaction === "save";
  const authors = authorLine(item.authors);
  const published = formatDate(item.published);
  const isPaper = item.kind === "paper";

  return (
    <article
      className={cn(
        "p-4 sm:p-6 hover:bg-gray-50/50 transition-all",
        item.reaction === "not_me" && "opacity-50 hover:opacity-80",
      )}
    >
      <div className="flex gap-3 sm:gap-4">
        <div className="w-10 h-10 sm:w-12 sm:h-12 rounded-full flex-shrink-0 bg-primary/20 text-yellow-700 flex items-center justify-center">
          <Icon size={20} strokeWidth={2.5} />
        </div>

        <div className="flex-1 min-w-0 space-y-3">
          {/* Source, kind, date, match */}
          <div className="flex justify-between items-start gap-3">
            <div className="flex items-center gap-x-2 gap-y-1 flex-wrap min-w-0">
              <span className="font-bold text-text-primary truncate">{sourceLabel(item.source)}</span>
              <span className="text-xs font-bold uppercase tracking-wider text-text-secondary bg-gray-100 px-2 py-0.5 rounded-full">
                {item.kind}
              </span>
              {published && <span className="text-text-secondary text-sm">· {published}</span>}
              {item.opened && <span className="text-text-secondary text-sm">· opened</span>}
            </div>
            <span className="bg-primary/20 text-yellow-700 text-xs font-bold px-2 py-1 rounded-full whitespace-nowrap">
              Match: {percent(item.score)}%
            </span>
          </div>

          {/* Why it matters to me */}
          {item.why && <p className="text-lg text-text-primary leading-relaxed">{item.why}</p>}

          {(item.interest || item.explore) && (
            <div className="flex flex-wrap gap-2">
              {item.interest && (
                <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-zinc-100 text-zinc-600 max-w-full">
                  <Hash className="w-3 h-3 mr-1 flex-shrink-0" />
                  <span className="truncate">{item.interest}</span>
                </span>
              )}
              {item.explore && (
                <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-sky-100 text-sky-800">
                  <Compass className="w-3 h-3 mr-1" />
                  Explore
                </span>
              )}
            </div>
          )}

          {/* Papers get the citation card; news and posts a plain card. */}
          <div
            className={cn(
              "p-4 rounded-xl transition-colors group relative",
              isPaper
                ? "bg-primary/10 border-2 border-primary/20 hover:bg-primary/20"
                : "bg-surface border border-gray-100 shadow-sm hover:bg-gray-50",
            )}
          >
            {saved && (
              <div className="absolute top-4 right-4 bg-primary text-text-primary text-xs font-bold px-2 py-1 rounded-full flex items-center gap-1">
                <Bookmark size={12} fill="currentColor" />
                Saved
              </div>
            )}
            <h3
              className={cn(
                "font-bold text-text-primary mb-1 group-hover:underline decoration-primary break-words",
                isPaper ? "text-xl" : "text-lg",
                saved && "pr-20",
              )}
            >
              <TitleLink item={item} onOpen={onOpen} />
            </h3>
            {authors && (
              <div className="text-text-secondary truncate" title={item.authors?.join(", ")}>
                {authors}
              </div>
            )}
            {item.summary && (
              <p className="text-sm text-text-secondary/90 leading-relaxed line-clamp-3 mt-2 break-words">
                {item.summary}
              </p>
            )}
          </div>

          {/* Reactions */}
          <div className="flex gap-2 sm:gap-6 pt-1 text-text-secondary">
            {ACTIONS.map((a) => {
              const active = item.reaction === a.reaction;
              const [text, circle] = active ? a.active : a.idle;
              return (
                <button
                  key={a.reaction}
                  onClick={() => onReact(item, a.reaction)}
                  aria-pressed={active}
                  className={cn("flex items-center gap-1 group transition-colors whitespace-nowrap", text)}
                >
                  <div className={cn("p-2 rounded-full transition-colors", circle)}>
                    <a.icon size={20} fill={active && a.reaction === "save" ? "currentColor" : "none"} />
                  </div>
                  <span className="text-sm font-medium">{a.label}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </article>
  );
}
