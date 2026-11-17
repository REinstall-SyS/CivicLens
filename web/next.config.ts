import type { NextConfig } from 'next';

const config: NextConfig = {
  output: process.env.NEXT_STANDALONE === '1' ? 'standalone' : undefined,
  agentRules: false,
  poweredByHeader: false,
  async rewrites() {
    return [{
      source: '/api/civic/:path*',
      destination: `${process.env.API_INTERNAL_URL ?? 'http://127.0.0.1:8000'}/v1/:path*`,
    }];
  },
};

export default config;
