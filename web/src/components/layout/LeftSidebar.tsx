import { RefreshCw } from "lucide-react";

import { cn } from "@/lib/utils";

import { NAV_ITEMS, type View } from "./nav";

interface LeftSidebarProps {
  onNavigate: (view: View) => void;
  currentView: View;
  hasNew?: boolean;
  onRefresh?: () => void;
}

export function LeftSidebar({ onNavigate, currentView, hasNew = false, onRefresh }: LeftSidebarProps) {
  return (
    <aside className="w-[275px] flex-shrink-0 sticky top-0 h-screen p-4 flex-col justify-between hidden md:flex">
      <div>
        <div className="p-4 mb-4">
          <div className="w-12 h-12 bg-primary rounded-xl flex items-center justify-center text-surface text-2xl font-bold">
            Δ
          </div>
        </div>

        <nav className="space-y-2">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              aria-current={currentView === item.id ? "page" : undefined}
              className={cn(
                "flex items-center gap-4 p-4 text-xl font-medium w-full text-left rounded-xl transition-colors",
                currentView === item.id
                  ? "bg-primary text-text-primary shadow-soft"
                  : "text-text-primary hover:bg-white/50",
              )}
            >
              <item.icon size={28} strokeWidth={2.5} />
              <span>{item.label}</span>
              {item.id === "feed" && hasNew && (
                <span className="ml-auto w-2.5 h-2.5 rounded-full bg-text-primary" aria-label="New items" />
              )}
            </button>
          ))}
        </nav>
      </div>

      <button
        onClick={onRefresh}
        className="w-full bg-primary text-text-primary font-bold text-xl py-4 rounded-3xl shadow-soft hover:bg-yellow-400 transition-colors flex items-center justify-center gap-2"
      >
        <RefreshCw size={20} strokeWidth={2.5} />
        Refresh
      </button>
    </aside>
  );
}
