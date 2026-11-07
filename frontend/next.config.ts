import type { NextConfig } from "next";

// The browser only talks to Next.js. Next.js forwards /api/* to the Python backend on
// localhost, so the page never calls anything else and the backend needs no CORS.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
// Requests through this proxy skip the outbound log, so it may only point at this machine.
if (!["localhost", "127.0.0.1", "[::1]"].includes(new URL(BACKEND_URL).hostname)) {
  throw new Error(`BACKEND_URL must point at localhost, got ${BACKEND_URL}`);
}

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
