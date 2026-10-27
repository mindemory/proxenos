import { cn } from "@/lib/utils";

import { NAV_ITEMS, type View } from "./nav";

interface MobileNavProps {
  onNavigate: (view: View) => void;
  currentView: View;
  hasNew?: boolean;
}

/** Bottom tab bar below the md breakpoint, where the left sidebar is hidden. */
export function MobileNav({ onNavigate, currentView, hasNew = false }: MobileNavProps) {
  return (
    <nav className="md:hidden fixed bottom-0 inset-x-0 z-50 bg-background/90 backdrop-blur-md border-t border-gray-200 flex justify-around px-2 pt-2 pb-[max(0.5rem,env(safe-area-inset-bottom))]">
      {NAV_ITEMS.map((item) => (
        <button
          key={item.id}
          onClick={() => onNavigate(item.id)}
          aria-current={currentView === item.id ? "page" : undefined}
          className={cn(
            "relative flex flex-col items-center gap-0.5 px-4 py-1.5 rounded-xl text-xs font-medium transition-colors",
            currentView === item.id ? "bg-primary text-text-primary" : "text-text-secondary",
          )}
        >
          <item.icon size={22} strokeWidth={2.5} />
          <span>{item.label}</span>
          {item.id === "feed" && hasNew && (
            <span className="absolute top-1 right-3 w-2 h-2 rounded-full bg-text-primary" aria-label="New items" />
          )}
        </button>
      ))}
    </nav>
  );
}
