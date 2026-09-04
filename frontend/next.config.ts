import type { NextConfig } from "next";

// The frontend is entirely client-side after the initial page load, so export
// static files for Nginx. This removes the need to keep a Node.js web process
// running on the production server.
const nextConfig: NextConfig = {
  output: "export",
};

export default nextConfig;
