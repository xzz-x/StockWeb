import type { NextConfig } from "next";

// Export directory-style static routes so Nginx can serve /fund-flow/,
// /limit-up/ and /daily-review/ as <route>/index.html without relying on
// SPA fallbacks. This avoids 403 responses when Nginx resolves a route path
// to an exported directory.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
};

export default nextConfig;
