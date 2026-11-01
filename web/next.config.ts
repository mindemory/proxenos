import type { NextConfig } from "next";

// Local only: the dev and start scripts bind to 127.0.0.1:4747. PROXENOS_STANDALONE=1 builds the
// page as a server of its own in .next/standalone, for the desktop app (desktop/build.sh), which
// runs it with Electron's Node on the port it picks; nothing else needs it.
const standalone = process.env.PROXENOS_STANDALONE === "1";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // The floating dev badge sits on top of the mobile tab bar.
  devIndicators: false,
  // Traced from web/ itself, so the server is .next/standalone/server.js whatever folder holds it.
  ...(standalone ? { output: "standalone", outputFileTracingRoot: __dirname } : {}),
};

export default nextConfig;
