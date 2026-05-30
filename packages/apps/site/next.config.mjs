import { createMDX } from 'fumadocs-mdx/next';

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: ['127.0.0.1'],
  transpilePackages: ['@flinttrade/design-system'],
  // DS-CSP-03: honour the per-request `x-csp-nonce` middleware sets, so Next 16's
  // framework-emitted (hydration/bootstrap) <script> tags inherit the nonce and run
  // under the nonce-based CSP without any 'unsafe-inline' allowance.
  experimental: {
    nonce: true,
  },
  images: {
    localPatterns: [
      {
        pathname: '/flinttrade/**',
      },
      {
        pathname: '/flinttrade/**',
        search: '?v=20260529',
      },
    ],
    remotePatterns: [],
  },
};

const withMDX = createMDX();

export default withMDX(nextConfig);
