import type { Metadata } from 'next';
import { GeistMono, GeistSans } from 'geist/font';
import { RootProvider } from 'fumadocs-ui/provider/next';
import type { ReactNode } from 'react';
import { SpeedInsights } from '@vercel/speed-insights/next';

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

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`} suppressHydrationWarning>
      <body>
        <RootProvider>{children}</RootProvider>
        <SpeedInsights />
      </body>
    </html>
  );
}
