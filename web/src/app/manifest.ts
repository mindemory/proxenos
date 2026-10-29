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
    // On a phone, the installed app is in the share sheet: what's shared to it is asked about.
    share_target: {
      action: "/share",
      method: "POST",
      enctype: "multipart/form-data",
      params: {
        title: "title",
        text: "text",
        url: "url",
        files: [{ name: "images", accept: ["image/png", "image/jpeg", "image/webp"] }],
      },
    },
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
