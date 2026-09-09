import type { Metadata } from 'next';
import { GeistMono, GeistSans } from 'geist/font';
import { RootProvider } from 'fumadocs-ui/provider/next';
import { headers } from 'next/headers';
import type { ReactNode } from 'react';

import { OptionalSpeedInsights } from '@/components/optional-speed-insights';
import { siteMetadataOrigin } from '@/lib/site-origin';

import './globals.css';

// Canonical fallback https://flinttrade.vercel.app is applied inside
// siteMetadataOrigin() when FLINTTRADE_SITE_URL / NEXT_PUBLIC_SITE_URL are unset.
export const metadata: Metadata = {
  title: {
    default: 'FlintTrade',
    template: '%s | FlintTrade',
  },
  description: 'Open-source self-hosted trading software built with Python, React, TypeScript, and Rust.',
  metadataBase: new URL(siteMetadataOrigin()),
  icons: {
    icon: '/flinttrade/logo.svg',
  },
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  // DS-CSP-03: read the per-request nonce the proxy set so RootProvider's
  // theme bootstrap and framework scripts can run without 'unsafe-inline'.
  const nonce = (await headers()).get('x-nonce') ?? '';

  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable}`}
      data-scroll-behavior="smooth"
      data-density="comfortable"
      suppressHydrationWarning
    >
      <body>
        <RootProvider theme={{ nonce }}>{children}</RootProvider>
        <OptionalSpeedInsights />
      </body>
    </html>
  );
}
