"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { ArrowUp } from "lucide-react";

import { Feed, type Tab } from "@/components/feed/Feed";
import { MobileNav } from "@/components/layout/MobileNav";
import { NAV_ITEMS, NETWORK_TABS, type NavCounts, type NetworkTab, type View } from "@/components/layout/nav";
import { Rail } from "@/components/layout/Rail";
import { Segmented } from "@/components/layout/Segmented";
import { TopBar } from "@/components/layout/TopBar";
import {
  DraftSkeleton,
  FeedSkeleton,
  GraphSkeleton,
  ProseSkeleton,
  ResultSkeleton,
  StatusSkeleton,
  TaskSkeleton,
} from "@/components/Skeleton";
import { Home } from "@/components/views/Home";
import type { MemoryIntent } from "@/components/views/Memory";
import { useHome, useItems } from "@/lib/client";

// Home and the feed come with the page; every other view loads the first time it's opened,
// with its own skeleton meanwhile, so the app's first paint carries only what it shows.
const Ask = dynamic(() => import("@/components/views/Ask").then((m) => m.Ask), {
  loading: () => <ProseSkeleton label="Loading ask" />,
});
const Errands = dynamic(() => import("@/components/views/Errands").then((m) => m.Errands), {
  loading: () => <ProseSkeleton label="Loading errands" />,
});
const Saved = dynamic(() => import("@/components/views/Saved").then((m) => m.Saved), {
  loading: () => <FeedSkeleton label="Loading saved items" />,
});
const Tasks = dynamic(() => import("@/components/views/Tasks").then((m) => m.Tasks), { loading: () => <TaskSkeleton /> });
const Care = dynamic(() => import("@/components/views/Care").then((m) => m.Care), {
  loading: () => <ProseSkeleton label="Loading care" />,
});
const Drafts = dynamic(() => import("@/components/views/Drafts").then((m) => m.Drafts), { loading: () => <DraftSkeleton /> });
const Advice = dynamic(() => import("@/components/views/Advice").then((m) => m.Advice), {
  loading: () => <ProseSkeleton label="Loading advice" />,
});
const Network = dynamic(() => import("@/components/views/Network").then((m) => m.Network), { loading: () => <GraphSkeleton /> });
const Memory = dynamic(() => import("@/components/views/Memory").then((m) => m.Memory), { loading: () => <ResultSkeleton /> });
const Profile = dynamic(() => import("@/components/views/Profile").then((m) => m.Profile), {
  loading: () => <ProseSkeleton label="Loading the profile" />,
});
const Connect = dynamic(() => import("@/components/views/Connect").then((m) => m.Connect), { loading: () => <StatusSkeleton /> });
const Settings = dynamic(() => import("@/components/views/Settings").then((m) => m.Settings), { loading: () => <StatusSkeleton /> });
const Status = dynamic(() => import("@/components/views/Status").then((m) => m.Status), { loading: () => <StatusSkeleton /> });

const TABS: { id: Tab; label: string }[] = [
  { id: "for_you", label: "For you" },
  { id: "explore", label: "Explore" },
];

/** Views that read as a single column of text, so they sit in a centred column, not across the canvas. */
const COLUMN_VIEWS: readonly View[] = ["ask", "errands", "feed", "saved", "tasks", "care", "advice", "profile", "connect", "settings", "status"];

export default function AppPage() {
  const [view, setView] = useState<View>("home");
  const [tab, setTab] = useState<Tab>("for_you");
  const [netTab, setNetTab] = useState<NetworkTab>("graph");
  // A person to find in the graph. Each request has a new nonce so asking again finds again.
  // The graph clears it once used, so coming back to the graph later doesn't find them again.
  const [find, setFind] = useState<{ q: string; nonce: number } | null>(null);
  const findCount = useRef(0);
  const found = useCallback(() => setFind(null), []);
  // A search or a record the command box or home page wants the memory view to open. The view
  // takes it on mount and clears it; the key makes a new request start a fresh view.
  const [memoryIntent, setMemoryIntent] = useState<MemoryIntent | null>(null);
  const [memoryKey, setMemoryKey] = useState(0);
  const memoryConsumed = useCallback(() => setMemoryIntent(null), []);
  // Bumped by Refresh: remounting the view makes it fetch again.
  const [refreshKey, setRefreshKey] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const feed = useItems("/api/items?batches=3", true);
  const home = useHome();

  // A link can open a view: /app?view=ask, which is where a share from the phone lands. Read
  // after the first paint, so the server's render (home) and the browser's first one agree.
  useEffect(() => {
    const asked = new URLSearchParams(window.location.search).get("view");
    const known = NAV_ITEMS.find((item) => item.id === asked);
    if (!known) return;
    const frame = requestAnimationFrame(() => setView(known.id));
    return () => cancelAnimationFrame(frame);
  }, []);

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

  const openMemory = (q: string, id?: string) => {
    setMemoryIntent({ q, id: id ?? null });
    setMemoryKey((k) => k + 1);
    navigate("memory");
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
        return <Home home={home} onNavigate={navigate} onMemory={openMemory} />;
      case "ask":
        return <Ask onNavigate={navigate} />;
      case "errands":
        return <Errands />;
      case "saved":
        return <Saved />;
      case "tasks":
        return <Tasks onChange={home.reload} />;
      case "care":
        return <Care onChange={home.reload} onMemory={openMemory} />;
      case "drafts":
        return <Drafts onChange={home.reload} />;
      case "advice":
        return <Advice onChange={home.reload} />;
      case "network":
        return <Network tab={netTab} onChange={home.reload} find={find} onFound={found} onTab={setNetTab} />;
      case "memory":
        return <Memory key={memoryKey} initial={memoryIntent} onConsumed={memoryConsumed} />;
      case "profile":
        return <Profile />;
      case "connect":
        return <Connect />;
      case "settings":
        return <Settings />;
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

  const navItem = NAV_ITEMS.find((n) => n.id === view);
  const title = navItem?.label;
  const group = navItem?.group === "you" ? "You" : navItem?.group === "home" ? "Your twin" : "Clones";
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
          onMemory={openMemory}
          onRefresh={refresh}
        />

        {view !== "home" && (
          <div className="flex min-h-[3.75rem] items-center justify-between gap-3 border-b border-line px-4 py-2 sm:px-6">
            <div className={`min-w-0 ${tabs ? "hidden sm:block" : ""}`}>
              <p className="smallcaps text-faint">{group}</p>
              <h1 className="title-2 truncate text-2xl">{title}</h1>
            </div>
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
              <div className="mx-auto w-full max-w-3xl md:border-x border-line min-h-[calc(100dvh-7.25rem)]">
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
