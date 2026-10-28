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
    <nav
      aria-label="Views"
      className="md:hidden fixed bottom-0 inset-x-0 z-50 bg-bg/90 backdrop-blur-md border-t border-line grid grid-cols-8 gap-0.5 px-1 pt-1.5 pb-[max(0.4rem,env(safe-area-inset-bottom))]"
    >
      {NAV_ITEMS.map((item) => {
        const active = currentView === item.id;
        return (
          <button
            key={item.id}
            onClick={() => onNavigate(item.id)}
            aria-current={active ? "page" : undefined}
            className={cn(
              "relative flex min-w-0 flex-col items-center gap-0.5 rounded-xl py-1.5 text-[10px] tracking-tight transition-colors",
              active ? "bg-surface text-accent" : "text-muted",
            )}
          >
            <item.icon size={20} strokeWidth={2} />
            <span className="max-w-full truncate">{item.label}</span>
            {item.id === "feed" && hasNew && (
              <span className="absolute top-1 right-[22%] w-1.5 h-1.5 rounded-full bg-accent" aria-label="New items" />
            )}
          </button>
        );
      })}
    </nav>
  );
}
