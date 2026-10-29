import { redirect } from "next/navigation";

import { setupNeeded } from "@/lib/setup";

// Read on every request, so the first run is noticed as soon as the settings are gone.
export const dynamic = "force-dynamic";

/** The app, unless this is a first run (no name and no vault set anywhere): then the setup page. */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  if (setupNeeded()) redirect("/setup");
  return children;
}
