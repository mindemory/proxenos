import type { Metadata, Viewport } from "next";
import { EB_Garamond, Geist, Geist_Mono, Newsreader } from "next/font/google";

import { ToastProvider } from "@/components/Toasts";

import "./globals.css";

const sans = Geist({ subsets: ["latin"], variable: "--font-geist" });
const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono" });
const display = Newsreader({
  subsets: ["latin"],
  variable: "--font-newsreader",
  axes: ["opsz"],
  style: ["normal", "italic"],
});
// The wordmark's face. Greek too, for the word the name comes from.
const brand = EB_Garamond({
  subsets: ["latin", "greek"],
  variable: "--font-garamond",
  style: ["normal", "italic"],
});

export const metadata: Metadata = {
  title: "Proxenos",
  description: "Proxenos acts on your behalf: a local briefing, research feed, tasks, drafts, network and memory.",
  robots: { index: false, follow: false },
};

// Always dark, so the browser chrome matches the ground.
export const viewport: Viewport = {
  themeColor: "#0e1013",
  colorScheme: "dark",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${sans.variable} ${mono.variable} ${display.variable} ${brand.variable}`}
    >
      <body suppressHydrationWarning className="antialiased bg-bg text-ink font-sans">
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
