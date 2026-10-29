import type { Metadata } from "next";

import { Setup } from "@/components/setup/Setup";

export const metadata: Metadata = { title: "Set up · Proxenos" };

/** First-run setup: your name, the vault, a model, then on to Connect. /app sends a first run here. */
export default function SetupPage() {
  return <Setup />;
}
