import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Docker consumes Next's standalone bundle; Vercel performs its own tracing.
  output: process.env.VERCEL ? undefined : "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
};

export default nextConfig;
