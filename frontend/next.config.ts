import type { NextConfig } from "next";

// The browser only talks to Next.js. Next.js forwards /api/* to the Python backend on
// localhost, so the page never calls anything else and the backend needs no CORS.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  experimental: {
    // The rewrite proxy gives up after 30 seconds by default. A scan that runs every page
    // through the local LLM can take minutes, so allow up to 10.
    proxyTimeout: 10 * 60 * 1000,
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
};

export default nextConfig;
