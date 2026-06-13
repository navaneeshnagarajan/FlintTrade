import { createMDX } from 'fumadocs-mdx/next';

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: ['127.0.0.1'],
  transpilePackages: ['@flinttrade/design-system'],
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
      // SPA fallback for the embedded Explore-mode terminal build under
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
        // Scoped CSP for the embedded terminal demo: same-origin only, but
        // runtime-injected styles allowed (Dockview/Plotly/inline keyframes)
        // and frameable by the site itself (/demo iframes it).
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
              "frame-ancestors 'self'",
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
