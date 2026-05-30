import type { Metadata } from 'next';
import { GeistMono, GeistSans } from 'geist/font';
import { RootProvider } from 'fumadocs-ui/provider/next';
import { headers } from 'next/headers';
import type { ReactNode } from 'react';

import './globals.css';

export const metadata: Metadata = {
  title: {
    default: 'FlintTrade',
    template: '%s | FlintTrade',
  },
  description: 'Open-source modular trading platform for Indian F&O, commodities, and crypto.',
  metadataBase: new URL('https://flinttrade.dev'),
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
      </body>
    </html>
  );
}
