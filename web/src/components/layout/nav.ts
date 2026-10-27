import { Activity, Bookmark, Home, UserRound } from "lucide-react";

export type View = "feed" | "saved" | "twin" | "status";

export const NAV_ITEMS = [
  { icon: Home, label: "Feed", id: "feed" },
  { icon: Bookmark, label: "Saved", id: "saved" },
  { icon: UserRound, label: "Twin", id: "twin" },
  { icon: Activity, label: "Status", id: "status" },
] as const satisfies readonly { icon: unknown; label: string; id: View }[];
