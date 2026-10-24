import type { NextConfig } from "next";

// TypeScript config (supported since Next.js 15). Replaces next.config.mjs so the
// project contains no script file types that email providers block.
const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // ".nosync": iCloud Drive skips these folders. Synced build output got "name 2" conflict copies
  // that broke typecheck and Turbopack's cache. e2e builds use their own folder (playwright.config.ts);
  // Docker sets NEXT_DIST_DIR=.next.
  distDir: process.env.NEXT_DIST_DIR || ".next.nosync",
};

export default nextConfig;
