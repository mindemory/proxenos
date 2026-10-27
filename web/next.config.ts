import type { NextConfig } from "next";

// Local only: the dev and start scripts bind to 127.0.0.1:4747.
const nextConfig: NextConfig = {
  poweredByHeader: false,
  // The floating dev badge sits on top of the mobile tab bar.
  devIndicators: false,
};

export default nextConfig;
