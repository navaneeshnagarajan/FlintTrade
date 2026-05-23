import { createMDX } from 'fumadocs-mdx/next';

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: ['127.0.0.1'],
  transpilePackages: ['@flinttrade/design-system'],
  images: {
    remotePatterns: [],
  },
};

const withMDX = createMDX();

export default withMDX(nextConfig);
