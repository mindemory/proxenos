"use client";

import { useState } from "react";
import { ArrowUp } from "lucide-react";

import { Feed, type Tab } from "@/components/feed/Feed";
import { LeftSidebar } from "@/components/layout/LeftSidebar";
import { MobileNav } from "@/components/layout/MobileNav";
import { NAV_ITEMS, type View } from "@/components/layout/nav";
import { RightSidebar } from "@/components/layout/RightSidebar";
import { Saved } from "@/components/views/Saved";
import { Status } from "@/components/views/Status";
import { Twin } from "@/components/views/Twin";
import { useItems } from "@/lib/client";
import { cn } from "@/lib/utils";

const TABS: { id: Tab; label: string }[] = [
  { id: "for_you", label: "For you" },
  { id: "explore", label: "Explore" },
];

export default function Home() {
  const [view, setView] = useState<View>("feed");
  const [tab, setTab] = useState<Tab>("for_you");
  const feed = useItems("/api/items?batches=3", true);

  const navigate = (next: View) => {
    setView(next);
    // Reactions made in Saved should show when coming back.
    if (next === "feed") feed.check();
    window.scrollTo({ top: 0 });
  };

  const showNew = () => {
    feed.showPending();
    setView("feed");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const renderView = () => {
    switch (view) {
      case "saved":
        return <Saved />;
      case "twin":
        return <Twin />;
      case "status":
        return <Status />;
      default:
        return <Feed data={feed.data} error={feed.error} tab={tab} onReact={feed.react} onOpen={feed.open} />;
    }
  };

  return (
    <div className="flex min-h-screen max-w-7xl mx-auto bg-background">
      <LeftSidebar
        onNavigate={navigate}
        currentView={view}
        hasNew={feed.pending !== null}
        onRefresh={() => {
          feed.refresh();
          setView("feed");
        }}
      />

      <main className="flex-1 min-w-0 border-x border-gray-200 min-h-screen relative">
        <header className="sticky top-0 bg-background/80 backdrop-blur-md z-40 border-b border-gray-100 p-4 flex justify-between items-center">
          {view === "feed" ? (
            <div className="flex bg-gray-100 p-1 rounded-xl max-w-md mx-auto w-full md:w-auto">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  aria-pressed={tab === t.id}
                  className={cn(
                    "flex-1 px-6 py-2 rounded-lg font-bold transition-all whitespace-nowrap",
                    tab === t.id ? "bg-white shadow-sm text-text-primary" : "text-text-secondary hover:text-text-primary",
                  )}
                >
                  {t.label}
                </button>
              ))}
            </div>
          ) : (
            <h1 className="text-2xl font-bold text-text-primary py-1.5 px-2">
              {NAV_ITEMS.find((n) => n.id === view)?.label}
            </h1>
          )}

          {feed.pending && (
            <button
              onClick={showNew}
              className="absolute left-1/2 -translate-x-1/2 top-full mt-3 flex items-center gap-1.5 bg-primary text-text-primary font-bold text-sm px-4 py-1.5 rounded-full shadow-md hover:bg-yellow-400 transition-colors whitespace-nowrap"
            >
              <ArrowUp size={16} strokeWidth={2.5} />
              New items
            </button>
          )}
        </header>

        {renderView()}
      </main>

      <RightSidebar feed={feed.data} />
      <MobileNav onNavigate={navigate} currentView={view} hasNew={feed.pending !== null} />
    </div>
  );
}
