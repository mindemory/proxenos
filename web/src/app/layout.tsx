import type { Metadata, Viewport } from "next";
import {
  Atkinson_Hyperlegible_Mono,
  Atkinson_Hyperlegible_Next,
  EB_Garamond,
  Geist,
  Geist_Mono,
  Newsreader,
} from "next/font/google";

import { ServiceWorker } from "@/components/ServiceWorker";
import { ToastProvider } from "@/components/Toasts";
import { READING_SCRIPT } from "@/lib/readingScript";

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
// The hyperlegible faces, for readers who pick them in Settings, Reading. Not preloaded: the
// browser fetches them (from this page, never Google) only once something is set in them.
const atkinson = Atkinson_Hyperlegible_Next({
  subsets: ["latin", "latin-ext"],
  variable: "--font-atkinson",
  style: ["normal", "italic"],
  preload: false,
});
const atkinsonMono = Atkinson_Hyperlegible_Mono({
  subsets: ["latin"],
  variable: "--font-atkinson-mono",
  preload: false,
});

export const metadata: Metadata = {
  title: "Proxenos",
  description: "Proxenos acts on your behalf: a local briefing, research feed, tasks, drafts, network and memory.",
  robots: { index: false, follow: false },
  appleWebApp: { capable: true, title: "Proxenos", statusBarStyle: "black-translucent" },
};

// Dark, so the browser chrome matches the ground. A light theme picked in Settings sets its own
// color-scheme in CSS and the chrome's colour once the page is up (lib/reading.ts).
export const viewport: Viewport = {
  themeColor: "#111111",
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
      className={`${sans.variable} ${mono.variable} ${display.variable} ${brand.variable} ${atkinson.variable} ${atkinsonMono.variable}`}
    >
      <head>
        {/* Runs before the page paints: this device's reading settings, from the first frame. */}
        <script dangerouslySetInnerHTML={{ __html: READING_SCRIPT }} />
      </head>
      <body suppressHydrationWarning className="antialiased bg-bg text-ink font-sans">
        <ToastProvider>{children}</ToastProvider>
        <ServiceWorker />
      </body>
    </html>
  );
}
