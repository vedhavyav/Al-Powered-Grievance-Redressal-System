import type { NextConfig } from "next";

// Automatically enable static HTML export on Cloudflare Pages or when explicitly requested
const isStaticExport = process.env.STATIC_EXPORT === "true" || process.env.CF_PAGES === "1";

const nextConfig: NextConfig = {
  ...(isStaticExport ? { output: "export" } : {}),
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
