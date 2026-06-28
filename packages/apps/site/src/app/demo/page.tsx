import type { Metadata } from 'next';

import { SiteFooter } from '@/components/site-footer';
import { SiteHeader } from '@/components/site-header';

export const metadata: Metadata = {
  title: 'Explore Demo',
  description:
    'Open the FlintTrade terminal in Explore mode with simulated data and no account or broker connection.',
};

export default function DemoPage() {
  return (
    <main className="site-shell">
      <SiteHeader />
      <section className="subpage subpage-tight">
        <h1>Explore Demo</h1>
        <p>
          This is the FlintTrade terminal running in Explore mode — the same React build you
          self-host, with simulated data. No account, broker connection, or backend needed.
        </p>
      </section>
      <div className="demo-frame-wrap">
        {/* No sandbox attribute: this is first-party same-origin content, and
            sandbox with allow-scripts + allow-same-origin is decorative (the
            framed doc keeps full origin authority). The scoped CSP on
            /demo-app is the real control. */}
        <iframe
          className="demo-frame"
          src="/demo-app/explore"
          title="FlintTrade terminal Explore demo"
          loading="lazy"
        />
        <p className="demo-note">
          All prices shown are sample data. Orders, automation, and broker connections are inert in
          Explore mode — install FlintTrade locally to go further with Practice and Live modes.
        </p>
      </div>
      <SiteFooter />
    </main>
  );
}
