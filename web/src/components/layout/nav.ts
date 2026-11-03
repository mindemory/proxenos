import {
  Activity,
  AudioWaveform,
  Bookmark,
  Brain,
  Clapperboard,
  Compass,
  FolderGit2,
  HeartPulse,
  House,
  Library,
  Lightbulb,
  ListTodo,
  NotebookPen,
  MessageSquare,
  MessagesSquare,
  Network,
  Phone,
  PenLine,
  Plug,
  Route,
  Rss,
  ShieldCheck,
  SlidersHorizontal,
  UserRound,
  type LucideIcon,
} from "lucide-react";

export type View =
  | "home"
  | "ask"
  | "think"
  | "errands"
  | "feed"
  | "saved"
  | "tasks"
  | "projects"
  | "care"
  | "drafts"
  | "advice"
  | "choices"
  | "watch"
  | "journal"
  | "life"
  | "rhythms"
  | "calls"
  | "network"
  | "memory"
  | "profile"
  | "connect"
  | "settings"
  | "privacy"
  | "status";

/** The sidebar's groups, by what the reader does there, the most used first and setup last. */
export type NavGroup = "today" | "think" | "work" | "life" | "setup";

export const NAV_GROUPS: readonly { id: NavGroup; label: string }[] = [
  { id: "today", label: "Today" },
  { id: "think", label: "Ask and think" },
  { id: "work", label: "Work" },
  { id: "life", label: "Your life" },
  { id: "setup", label: "Setup" },
];

export interface NavItem {
  icon: LucideIcon;
  label: string;
  id: View;
  group: NavGroup;
  /** Other words the command box finds it by. */
  words: string;
  /** A line under the view's name in its header, where the name alone doesn't say what's there. */
  blurb?: string;
}

/** Every view, in the order the sidebar, the phone's sheet and the command box list them. */
export const NAV_ITEMS: readonly NavItem[] = [
  { icon: House, label: "Home", id: "home", group: "today", words: "today brief briefing start overview" },
  { icon: PenLine, label: "Drafts", id: "drafts", group: "today", words: "messages replies email send outbox" },
  { icon: ListTodo, label: "Tasks", id: "tasks", group: "today", words: "todo to-do reminders due" },
  { icon: HeartPulse, label: "Care", id: "care", group: "today", words: "health doctor medical appointments insurance bills" },
  { icon: Route, label: "Errands", id: "errands", group: "today", words: "get done reach out cv" },
  { icon: Phone, label: "Calls", id: "calls", group: "today", words: "phone ring hold call sheet" },
  { icon: MessageSquare, label: "Ask", id: "ask", group: "think", words: "question answer chat draft a message" },
  { icon: MessagesSquare, label: "Think", id: "think", group: "think", words: "thread reflect think through decide" },
  { icon: Lightbulb, label: "Advice", id: "advice", group: "think", words: "advisor suggestions patterns" },
  { icon: Compass, label: "Choices", id: "choices", group: "think", words: "decisions openings invitations time" },
  {
    icon: FolderGit2,
    label: "Projects & papers",
    id: "projects",
    group: "work",
    words: "paper manuscript thesis work steps branches code repository analysis",
    blurb: "Each project's paper, its steps and their branches.",
  },
  { icon: Rss, label: "Feed", id: "feed", group: "work", words: "research papers arxiv articles new" },
  { icon: Bookmark, label: "Saved", id: "saved", group: "work", words: "bookmarks kept later" },
  { icon: Clapperboard, label: "Watch", id: "watch", group: "work", words: "films movies shows tv letterboxd" },
  { icon: NotebookPen, label: "Journal", id: "journal", group: "life", words: "diary day log" },
  { icon: Library, label: "Life", id: "life", group: "life", words: "story stories years months timeline" },
  { icon: AudioWaveform, label: "Rhythms", id: "rhythms", group: "life", words: "weeks habits listening music movement charts" },
  { icon: Network, label: "Network", id: "network", group: "life", words: "people contacts friends colleagues graph" },
  { icon: Brain, label: "Memory", id: "memory", group: "life", words: "search records history archive messages" },
  { icon: UserRound, label: "Profile", id: "profile", group: "life", words: "self-model about you interests" },
  { icon: Plug, label: "Connect", id: "connect", group: "setup", words: "sources accounts import add set up" },
  { icon: SlidersHorizontal, label: "Settings", id: "settings", group: "setup", words: "preferences options reading text size theme" },
  { icon: ShieldCheck, label: "Privacy", id: "privacy", group: "setup", words: "data local models what leaves delete" },
  { icon: Activity, label: "Status", id: "status", group: "setup", words: "sync synced last jobs errors" },
];

/** A group's label, as the sidebar and a view's header name it. */
export const groupLabel = (group: NavGroup) => NAV_GROUPS.find((g) => g.id === group)?.label ?? "";

/** The phone's tab bar: four views, then "More" for all of them by group. */
export const PRIMARY_MOBILE: readonly View[] = ["home", "drafts", "tasks", "network"];

/** Small counts shown beside nav entries. */
export type NavCounts = Partial<Record<View, number>>;

/** The network view's tabs. Here rather than in the view, so the page can name them without loading it. */
export type NetworkTab = "graph" | "list" | "projects" | "outreach";

export const NETWORK_TABS: { id: NetworkTab; label: string }[] = [
  { id: "graph", label: "Graph" },
  { id: "list", label: "List" },
  { id: "projects", label: "Projects" },
  { id: "outreach", label: "Reach out" },
];
