import {
  Activity,
  Bookmark,
  Brain,
  House,
  Lightbulb,
  ListTodo,
  Network,
  PenLine,
  Rss,
  UserRound,
  type LucideIcon,
} from "lucide-react";

export type View =
  | "home"
  | "feed"
  | "saved"
  | "tasks"
  | "drafts"
  | "advice"
  | "network"
  | "memory"
  | "twin"
  | "status";

export interface NavItem {
  icon: LucideIcon;
  label: string;
  id: View;
  /** Where it sits in the rail: the home button, the clones' views, and the views about you. */
  group: "home" | "clones" | "you";
}

export const NAV_ITEMS: readonly NavItem[] = [
  { icon: House, label: "Home", id: "home", group: "home" },
  { icon: Rss, label: "Feed", id: "feed", group: "clones" },
  { icon: Bookmark, label: "Saved", id: "saved", group: "clones" },
  { icon: ListTodo, label: "Tasks", id: "tasks", group: "clones" },
  { icon: PenLine, label: "Drafts", id: "drafts", group: "clones" },
  { icon: Lightbulb, label: "Advice", id: "advice", group: "clones" },
  { icon: Network, label: "Network", id: "network", group: "clones" },
  { icon: Brain, label: "Memory", id: "memory", group: "you" },
  { icon: UserRound, label: "Twin", id: "twin", group: "you" },
  { icon: Activity, label: "Status", id: "status", group: "you" },
];

/** The phone's tab bar: four views, then "More" for the rest. */
export const PRIMARY_MOBILE: readonly View[] = ["home", "tasks", "drafts", "network"];

/** Small counts shown beside nav entries. */
export type NavCounts = Partial<Record<View, number>>;
