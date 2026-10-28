import {
  Activity,
  Bookmark,
  House,
  Inbox,
  Lightbulb,
  ListTodo,
  Network,
  Rss,
  ShoppingBag,
  UserRound,
  type LucideIcon,
} from "lucide-react";

export type View = "home" | "feed" | "saved" | "tasks" | "advice" | "network" | "twin" | "status";

export interface NavItem {
  icon: LucideIcon;
  label: string;
  id: View;
  /** Built by a clone; listed under "Clones" in the sidebar. */
  clone?: boolean;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { icon: House, label: "Home", id: "home" },
  { icon: Rss, label: "Feed", id: "feed", clone: true },
  { icon: Bookmark, label: "Saved", id: "saved", clone: true },
  { icon: ListTodo, label: "Tasks", id: "tasks", clone: true },
  { icon: Lightbulb, label: "Advice", id: "advice", clone: true },
  { icon: Network, label: "Network", id: "network", clone: true },
  { icon: UserRound, label: "Twin", id: "twin" },
  { icon: Activity, label: "Status", id: "status" },
];

/** Clones that aren't built yet. Listed, disabled, so the nav shows what's coming. */
export const SOON_ITEMS: readonly { icon: LucideIcon; label: string }[] = [
  { icon: Inbox, label: "Inbox" },
  { icon: ShoppingBag, label: "Shopping" },
];

/** Small counts shown beside nav entries. */
export type NavCounts = Partial<Record<View, number>>;
