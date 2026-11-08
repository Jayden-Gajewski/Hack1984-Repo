import type { NextConfig } from "next";

// The browser only talks to Next.js. Next.js forwards /api/* to Dossier's Python backend, so the
// page never calls anything else and the backend needs no CORS. Locally the backend is on this
// machine; on the public site (docs/DEPLOY.md) it's the backend's own https address.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const backend = new URL(BACKEND_URL);
if (backend.protocol !== "https:" && !["localhost", "127.0.0.1", "[::1]"].includes(backend.hostname)) {
  throw new Error(`BACKEND_URL must be https unless it's on this machine, got ${BACKEND_URL}`);
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
