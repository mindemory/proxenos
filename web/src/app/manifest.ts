import type { MetadataRoute } from "next";

/** What makes the page installable as an app: from Chrome or Safari on the Mac, Chrome on a phone. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Proxenos",
    short_name: "Proxenos",
    description: "An agent that holds your entire record and acts on your behalf.",
    start_url: "/app",
    scope: "/",
    display: "standalone",
    background_color: "#0e1013",
    theme_color: "#0e1013",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
