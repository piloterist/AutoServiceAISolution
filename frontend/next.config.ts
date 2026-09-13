import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output keeps the production container image small and
  // self-contained (no node_modules copy needed at runtime).
  output: "standalone",
};

export default nextConfig;
