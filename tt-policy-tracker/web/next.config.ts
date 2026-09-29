import type { NextConfig } from "next";

// No rewrites. The browser reaches the Railway API only through the
// authenticated route handler at app/backend/[...path]/route.ts, which adds
// the X-Jeanne-Key header server-side. /api/auth/* belongs to Auth.js.
const nextConfig: NextConfig = {};

export default nextConfig;
