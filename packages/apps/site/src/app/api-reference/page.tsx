import { ArrowRight, Braces, Cable, KeyRound, Radio } from 'lucide-react';
import Link from 'next/link';

import { SiteFooter } from '@/components/site-footer';
import { SiteHeader } from '@/components/site-header';
import { getDoc } from '@/lib/mcp/capabilities';

const areas = [
  {
    icon: Braces,
    title: 'REST endpoints',
    copy: 'FlintTrade /ft-api/v1 endpoints and optional OpenAlgo-compatible bridge routes share one reference path.',
  },
  {
    icon: Radio,
    title: 'WebSocket contracts',
    copy: 'Streaming market data and gateway protocol details live beside the HTTP contract.',
  },
  {
    icon: KeyRound,
    title: 'Mode and auth model',
    copy: 'Explore, Practice, and Live behaviour is documented with server-side enforcement notes.',
  },
];

export const metadata = {
  title: 'API Reference',
  description: 'FlintTrade API reference overview for HTTP, WebSocket, and auth contracts.',
};

export default function ApiReferencePage() {
  const apiDoc = getDoc('api');
  const headings = apiDoc?.headings.slice(0, 10) ?? [];

  return (
    <main className="site-shell">
      <SiteHeader />
      <section className="subpage">
        <h1>API contracts for integrators.</h1>
        <p>
          The public site mirrors the repository API reference so endpoint docs, WebSocket behaviour, and
          auth notes stay close to implementation changes.
        </p>

        <div className="feature-grid">
          {areas.map((area) => {
            const Icon = area.icon;
            return (
              <article className="feature-card" key={area.title}>
                <Icon aria-hidden="true" />
                <h3>{area.title}</h3>
                <p>{area.copy}</p>
              </article>
            );
          })}
        </div>

        <div className="stack">
          <div className="code-panel">
            <header>
              <span>From docs/API.md</span>
              <span>{apiDoc?.sourcePath}</span>
            </header>
            <pre>{headings.map((heading) => `${'#'.repeat(heading.level)} ${heading.title}`).join('\n')}</pre>
          </div>
        </div>

        <div className="hero-actions">
          <Link className="button primary" href="/docs/api">
            Full API docs <ArrowRight aria-hidden="true" size={17} />
          </Link>
          <Link className="button secondary" href="/mcp">
            Query with MCP <Cable aria-hidden="true" size={17} />
          </Link>
        </div>
      </section>
      <SiteFooter />
    </main>
  );
}
