"use client";

import { useEffect } from "react";

/**
 * Registers /sw.js, which is what lets Chrome offer to install Proxenos as an app. Renders
 * nothing. A browser without service workers, or one that refuses, simply doesn't get the offer.
 */
export function ServiceWorker() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" }).catch(() => {
      // Not offered the install: the page works the same without it.
    });
  }, []);
  return null;
}
