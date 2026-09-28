import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  images: {
    unoptimized: true, // Required for static export on Cloudflare Pages
  },
};

export default nextConfig;
