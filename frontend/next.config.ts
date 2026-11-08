import type { NextConfig } from "next";

// The browser only talks to Next.js. Next.js forwards /api/* to Dossier's Python backend, so the
// page never calls anything else and the backend needs no CORS. Locally the backend is on this
// machine; on the public site (docs/DEPLOY.md) it's the backend's own https address.
// On Vercel there's no backend on the same machine: without BACKEND_URL every /api call would go
// to localhost and fail, so stop the build instead of deploying a site that can't sign anyone in.
if (process.env.VERCEL && !process.env.BACKEND_URL) {
  throw new Error("Set BACKEND_URL (the backend's https address) in the Vercel project's environment variables.");
}
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const backend = new URL(BACKEND_URL);
if (backend.protocol !== "https:" && !["localhost", "127.0.0.1", "[::1]"].includes(backend.hostname)) {
  throw new Error(`BACKEND_URL must be https unless it's on this machine, got ${BACKEND_URL}`);
}

const nextConfig: NextConfig = {
  reactStrictMode: true,
  experimental: {
    // `next start` gives up on the backend after 30 seconds by default, and a scan can take
    // minutes, so allow up to 10. Vercel ignores this: it stops waiting after 120 seconds. The
    // scan keeps running on the backend and is saved, so scanning again loads it.
    proxyTimeout: 10 * 60 * 1000,
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
};

export default nextConfig;
