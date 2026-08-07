import { createMDX } from 'fumadocs-mdx/next';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

/** @type {import('next').NextConfig} */
const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, '../../..');

const nextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: ['127.0.0.1'],
  transpilePackages: ['@flinttrade/design-system'],
  turbopack: {
    root: repoRoot,
  },
  images: {
    localPatterns: [
      {
        pathname: '/flinttrade/**',
      },
      {
        pathname: '/flinttrade/**',
        search: '?v=20260613',
      },
    ],
    remotePatterns: [],
  },
  async rewrites() {
    return {
      // SPA fallback for the full-page terminal demo build under
      // public/demo-app/ — real files win first, deep routes get index.html.
      afterFiles: [
        { source: '/demo-app', destination: '/demo-app/index.html' },
        { source: '/demo-app/:path*', destination: '/demo-app/index.html' },
      ],
    };
  },
  async headers() {
    return [
      {
        // Scoped CSP for the full-page terminal demo: same-origin only, but
        // runtime-injected styles allowed (Dockview/Plotly/inline keyframes)
        // and not frameable now that the site opens it as its own page.
        source: '/demo-app/:path*',
        headers: [
          {
            key: 'Content-Security-Policy',
            value: [
              "default-src 'self'",
              "script-src 'self'",
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data: blob:",
              "font-src 'self' data:",
              "connect-src 'self'",
              "frame-ancestors 'none'",
              "base-uri 'self'",
              "form-action 'self'",
              "object-src 'none'",
            ].join('; '),
          },
          {
            key: 'X-Content-Type-Options',
            value: 'nosniff',
          },
        ],
      },
    ];
  },
};

const withMDX = createMDX();

export default withMDX(nextConfig);
