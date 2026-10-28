"use client";

import { useCallback, useRef, useState } from "react";
import { ArrowUp } from "lucide-react";

import { Feed, type Tab } from "@/components/feed/Feed";
import { MobileNav } from "@/components/layout/MobileNav";
import { NAV_ITEMS, type NavCounts, type View } from "@/components/layout/nav";
import { Rail } from "@/components/layout/Rail";
import { Segmented } from "@/components/layout/Segmented";
import { TopBar } from "@/components/layout/TopBar";
import { Advice } from "@/components/views/Advice";
import { Drafts } from "@/components/views/Drafts";
import { Home } from "@/components/views/Home";
import { Network, NETWORK_TABS, type NetworkTab } from "@/components/views/Network";
import { Saved } from "@/components/views/Saved";
import { Status } from "@/components/views/Status";
import { Tasks } from "@/components/views/Tasks";
import { Twin } from "@/components/views/Twin";
import { useHome, useItems } from "@/lib/client";

const TABS: { id: Tab; label: string }[] = [
  { id: "for_you", label: "For you" },
  { id: "explore", label: "Explore" },
];

/** Views that read as a single column of text, so they sit in a centred column, not across the canvas. */
const COLUMN_VIEWS: readonly View[] = ["feed", "saved", "tasks", "advice", "twin", "status"];

export default function Page() {
  const [view, setView] = useState<View>("home");
  const [tab, setTab] = useState<Tab>("for_you");
  const [netTab, setNetTab] = useState<NetworkTab>("graph");
  // A person to find in the graph. Each request has a new nonce so asking again finds again.
  // The graph clears it once used, so coming back to the graph later doesn't find them again.
  const [find, setFind] = useState<{ q: string; nonce: number } | null>(null);
  const findCount = useRef(0);
  const found = useCallback(() => setFind(null), []);
  // Bumped by Refresh: remounting the view makes it fetch again.
  const [refreshKey, setRefreshKey] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
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

  const openNetworkTab = (t: NetworkTab) => {
    setNetTab(t);
    navigate("network");
  };

  const findPerson = (q: string) => {
    findCount.current += 1;
    setFind({ q, nonce: findCount.current });
    openNetworkTab("graph");
  };

  const showNew = () => {
    feed.showPending();
    setView("feed");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const refresh = () => {
    setRefreshing(true);
    Promise.allSettled([feed.refresh(), home.reload()]).finally(() => setRefreshing(false));
    setRefreshKey((k) => k + 1);
  };

  const counts: NavCounts = home.data
    ? {
        tasks: home.data.tasks.actionable.filter((t) => t.action === null).length,
        drafts: home.data.drafts.awaiting,
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
      case "drafts":
        return <Drafts onChange={home.reload} />;
      case "advice":
        return <Advice onChange={home.reload} />;
      case "network":
        return <Network tab={netTab} onChange={home.reload} find={find} onFound={found} onTab={setNetTab} />;
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

  const title = NAV_ITEMS.find((n) => n.id === view)?.label;
  const tabs =
    view === "feed" ? (
      <Segmented label="Feed" tabs={TABS} value={tab} onChange={setTab} />
    ) : view === "network" ? (
      <Segmented
        label="Network"
        tabs={NETWORK_TABS}
        value={netTab}
        onChange={(t) => {
          setNetTab(t);
          window.scrollTo({ top: 0 });
        }}
      />
    ) : null;
  const column = COLUMN_VIEWS.includes(view) || (view === "network" && netTab !== "graph");

  return (
    <div className="flex min-h-dvh">
      <Rail onNavigate={navigate} currentView={view} hasNew={feed.pending !== null} counts={counts} />

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar
          home={home}
          counts={counts}
          refreshing={refreshing}
          onNavigate={navigate}
          onFind={findPerson}
          onNetworkTab={openNetworkTab}
          onRefresh={refresh}
        />

        {view !== "home" && (
          <div className="flex h-[3.25rem] items-center justify-between gap-3 border-b border-line px-4 sm:px-6">
            <h1 className={`font-display text-2xl text-ink truncate ${tabs ? "hidden sm:block" : ""}`}>{title}</h1>
            {tabs}
          </div>
        )}

        <main className="relative min-w-0 flex-1">
          {feed.pending && (
            <button
              onClick={showNew}
              className="toast-in absolute left-1/2 top-3 z-30 flex -translate-x-1/2 items-center gap-1.5 whitespace-nowrap rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-accent-ink shadow-pop"
            >
              <ArrowUp size={15} strokeWidth={2.5} />
              New items
            </button>
          )}
          <div key={`${view}:${refreshKey}`} className="screen-in">
            {column ? (
              <div className="mx-auto w-full max-w-3xl md:border-x border-line min-h-[calc(100dvh-6.75rem)]">
                {renderView()}
              </div>
            ) : (
              renderView()
            )}
          </div>
        </main>
      </div>

      <MobileNav
        onNavigate={navigate}
        currentView={view}
        hasNew={feed.pending !== null}
        counts={counts}
        onRefresh={refresh}
      />
    </div>
  );
}
