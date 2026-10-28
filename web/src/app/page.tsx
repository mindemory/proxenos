"use client";

import { useState } from "react";
import { ArrowUp } from "lucide-react";

import { Feed, type Tab } from "@/components/feed/Feed";
import { LeftSidebar } from "@/components/layout/LeftSidebar";
import { MobileNav } from "@/components/layout/MobileNav";
import { NAV_ITEMS, type NavCounts, type View } from "@/components/layout/nav";
import { RightSidebar } from "@/components/layout/RightSidebar";
import { Logo } from "@/components/Logo";
import { Advice } from "@/components/views/Advice";
import { Home } from "@/components/views/Home";
import { Network, NETWORK_TABS, type NetworkTab } from "@/components/views/Network";
import { Saved } from "@/components/views/Saved";
import { Status } from "@/components/views/Status";
import { Tasks } from "@/components/views/Tasks";
import { Twin } from "@/components/views/Twin";
import { useHome, useItems } from "@/lib/client";
import { longDay } from "@/lib/format";
import { cn } from "@/lib/utils";

const TABS: { id: Tab; label: string }[] = [
  { id: "for_you", label: "For you" },
  { id: "explore", label: "Explore" },
];

/** The header's tab switch, used by views that have more than one list. */
function Segmented<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: string }[];
  value: T;
  onChange: (t: T) => void;
}) {
  return (
    <div className="flex min-w-0 bg-surface border border-line p-1 rounded-full">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          aria-pressed={value === t.id}
          className={cn(
            "px-3 sm:px-4 py-1 rounded-full text-sm transition-colors whitespace-nowrap",
            value === t.id ? "bg-surface-2 text-ink" : "text-muted hover:text-ink",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export default function Page() {
  const [view, setView] = useState<View>("home");
  const [tab, setTab] = useState<Tab>("for_you");
  const [netTab, setNetTab] = useState<NetworkTab>("people");
  // Bumped by Refresh: remounting the view makes it fetch again.
  const [refreshKey, setRefreshKey] = useState(0);
  const feed = useItems("/api/items?batches=3", true);
  const home = useHome();

  const navigate = (next: View) => {
    setView(next);
    // Reactions made in Saved should show when coming back.
    if (next === "feed") feed.check();
    // Actions taken in other views change the brief's counts.
    if (next === "home") home.reload();
    window.scrollTo({ top: 0 });
  };

  const showNew = () => {
    feed.showPending();
    setView("feed");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const refresh = () => {
    feed.refresh();
    home.reload();
    setRefreshKey((k) => k + 1);
  };

  const counts: NavCounts = home.data
    ? {
        tasks: home.data.tasks.actionable.filter((t) => t.action === null).length,
        advice: home.data.advice.unanswered,
      }
    : {};

  const renderView = () => {
    switch (view) {
      case "home":
        return <Home home={home} onNavigate={navigate} />;
      case "saved":
        return <Saved />;
      case "tasks":
        return <Tasks onChange={home.reload} />;
      case "advice":
        return <Advice onChange={home.reload} />;
      case "network":
        return <Network tab={netTab} onChange={home.reload} />;
      case "twin":
        return <Twin />;
      case "status":
        return <Status />;
      default:
        return (
          <Feed
            data={feed.data}
            error={feed.error}
            flashId={feed.flashId}
            tab={tab}
            onReact={feed.react}
            onOpen={feed.open}
            onDismissError={feed.clearError}
          />
        );
    }
  };

  const title =
    view === "home" && home.data ? longDay(home.data.now) : NAV_ITEMS.find((n) => n.id === view)?.label;

  return (
    <div className="flex min-h-screen max-w-7xl mx-auto">
      <LeftSidebar
        onNavigate={navigate}
        currentView={view}
        hasNew={feed.pending !== null}
        counts={counts}
        onRefresh={refresh}
      />

      <main className="flex-1 min-w-0 md:border-x border-line min-h-screen relative">
        <header className="sticky top-0 z-40 h-14 bg-bg/85 backdrop-blur-md border-b border-line px-4 sm:px-6 flex items-center justify-between gap-3">
          {view === "feed" ? (
            <Segmented tabs={TABS} value={tab} onChange={setTab} />
          ) : view === "network" ? (
            <Segmented tabs={NETWORK_TABS} value={netTab} onChange={(t) => (setNetTab(t), window.scrollTo({ top: 0 }))} />
          ) : (
            <h1 className="font-display text-2xl text-ink truncate">{title}</h1>
          )}

          <button onClick={() => navigate("home")} className="md:hidden rounded-full" aria-label="Twin, home">
            <Logo size={26} className="text-accent" />
          </button>

          {feed.pending && (
            <button
              onClick={showNew}
              className="toast-in absolute left-1/2 -translate-x-1/2 top-full mt-3 flex items-center gap-1.5 bg-accent text-accent-ink text-sm font-medium px-4 py-1.5 rounded-full shadow-pop whitespace-nowrap"
            >
              <ArrowUp size={15} strokeWidth={2.5} />
              New items
            </button>
          )}
        </header>

        <div key={`${view}:${refreshKey}`} className="screen-in">
          {renderView()}
        </div>
      </main>

      <RightSidebar feed={feed.data} home={home.data} onNavigate={navigate} />
      <MobileNav onNavigate={navigate} currentView={view} hasNew={feed.pending !== null} />
    </div>
  );
}
