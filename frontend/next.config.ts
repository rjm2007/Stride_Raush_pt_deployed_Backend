import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // The Docker image runs the self-contained server Next writes to .next/standalone.
  output: 'standalone',
};

export default nextConfig;
