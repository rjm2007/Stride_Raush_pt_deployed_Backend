import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // The Docker image runs the self-contained server Next writes to .next/standalone.
  output: 'standalone',
  experimental: {
    // Reuse a visited page for 5 minutes instead of asking the server again (Next's default for dynamic
    // pages is 0). Safe here because a cached page holds no patient data: the dashboard pages render
    // nothing (null) and the layout holds only the signed-in staff member and the staff roster. Every
    // lead, message and call is loaded through /api/dashboard, which checks the session cookie on each
    // request; a 401 there clears the data cache and assistant chats and sends the browser to /login
    // (dashboard-client.ts). Sign-out is a full page load, which empties this router cache too.
    staleTimes: {
      dynamic: 300,
      static: 300,
    },
  },
};

export default nextConfig;
