import { ArrowRight, Bot, Cable, ShieldCheck, TerminalSquare } from 'lucide-react';
import Image from 'next/image';
import Link from 'next/link';
import type { CSSProperties } from 'react';

import { SiteFooter } from '@/components/site-footer';
import { SiteHeader } from '@/components/site-header';
import { listPackages } from '@/lib/mcp/capabilities';

const featureCards = [
  {
    icon: TerminalSquare,
    title: 'A self-hosted trading cockpit',
    copy: 'React, Dockview, Python services, Rust tick processing, and OpenAlgo integration in one inspectable workspace.',
  },
  {
    icon: ShieldCheck,
    title: 'Safety before automation',
    copy: 'Explore, Practice, and Live modes keep learning, testing, and broker-connected workflows separated.',
  },
  {
    icon: Bot,
    title: 'Agent-ready contribution docs',
    copy: 'Generated docs indexes, llms files, and read-only MCP tools help contributors understand the repo before editing.',
  },
];

const docsCards = [
  { href: '/docs/user-guide', label: 'User Guide', copy: 'Install, connect, explore paper mode, and learn the workspace.' },
  { href: '/docs/developer-guide', label: 'Developer Guide', copy: 'Repo map, tests, coding style, widgets, strategies, and PR flow.' },
  { href: '/api-reference', label: 'API Reference', copy: 'OpenAlgo passthrough, FlintTrade endpoints, auth, and WebSocket contracts.' },
];

const meteorTracks = [8, 19, 31, 44, 58, 71, 84];
const wordmarkChars = 'FlintTrade'.split('');
const impactDebris = [
  ['-54px', '-38px'],
  ['48px', '-52px'],
  ['-44px', '34px'],
  ['62px', '28px'],
  ['-26px', '-62px'],
  ['38px', '52px'],
  ['-66px', '8px'],
  ['24px', '-66px'],
] as const;

export default function HomePage() {
  const packages = listPackages().slice(0, 8);

  return (
    <main className="site-shell">
      <div className="site-cinematic-backdrop" aria-hidden="true">
        {meteorTracks.map((left, index) => (
          <span
            className="site-meteor"
            key={left}
            style={{
              left: `${left}%`,
              animationDelay: `${index * 0.68}s`,
              animationDuration: `${4.1 + index * 0.36}s`,
            }}
          />
        ))}
      </div>
      <SiteHeader />

      <section className="section hero">
        <div className="hero-copy">
          <div className="hero-logo-stage" aria-hidden="true">
            <span className="site-hero-fireball" />
            <span className="site-impact-blast" />
            <span className="site-shock-ring" />
            <span className="site-shock-ring site-shock-ring-secondary" />
            {impactDebris.map(([dx, dy], index) => (
              <span
                className="site-impact-debris"
                key={`${dx}-${dy}`}
                style={{
                  '--dx': dx,
                  '--dy': dy,
                  animationDelay: `${1.34 + index * 0.025}s`,
                } as CSSProperties}
              />
            ))}
            <div className="hero-logo-mark hero-logo-reveal">
              <Image src="/flinttrade/logo.svg" alt="" width={86} height={86} priority />
            </div>
          </div>
          <h1 aria-label="FlintTrade">
            {wordmarkChars.map((char, index) => (
              <span
                aria-hidden="true"
                className="hero-title-char"
                key={`${char}-${index}`}
                style={{ animationDelay: `${1.95 + index * 0.055}s` }}
              >
                {char}
              </span>
            ))}
          </h1>
          <p>
            An open-source modular trading platform for Indian F&O, commodities, and crypto. It layers a
            keyboard-driven terminal, analytics, automation, and AI workflows over self-hosted OpenAlgo.
          </p>
          <div className="hero-actions">
            <Link className="button primary" href="/docs">
              Read the docs <ArrowRight aria-hidden="true" size={17} />
            </Link>
            <Link className="button secondary" href="/mcp">
              Use the docs MCP <Cable aria-hidden="true" size={17} />
            </Link>
          </div>
        </div>

        <div className="hero-visual" aria-label="FlintTrade terminal screenshots">
          <div className="screenshot-stack">
            <figure className="screen-frame main">
              <Image src="/flinttrade/screenshots/01-welcome.png" alt="FlintTrade cinematic welcome screen" fill priority sizes="(max-width: 900px) 100vw, 58vw" />
            </figure>
            <figure className="screen-frame side">
              <Image src="/flinttrade/screenshots/04-trade.png" alt="FlintTrade trade canvas" fill sizes="(max-width: 900px) 46vw, 22vw" />
            </figure>
            <figure className="screen-frame float">
              <Image src="/flinttrade/screenshots/06-lab.png" alt="Strategy lab" fill sizes="(max-width: 900px) 42vw, 20vw" />
            </figure>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="metric-rail" aria-label="Project facts">
          <div>
            <strong>32</strong>
            <span>OpenAlgo broker integrations documented for compatibility checks.</span>
          </div>
          <div>
            <strong>16</strong>
            <span>Packages across Python, React, Rust/PyO3, Chrome extension, and Tauri.</span>
          </div>
          <div>
            <strong>82</strong>
            <span>Terminal widgets described by the public contributor documentation.</span>
          </div>
          <div>
            <strong>AGPL</strong>
            <span>Network-use source sharing keeps the self-hosted stack accountable.</span>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="section-heading">
          <h2>Built for people who read the source.</h2>
          <p>
            The public site stays close to the repository. Root docs, package READMEs, screenshots, and
            contribution commands are generated into the site rather than rewritten in a second place.
          </p>
        </div>
        <div className="feature-grid">
          {featureCards.map((card) => {
            const Icon = card.icon;
            return (
              <article className="feature-card" key={card.title}>
                <Icon aria-hidden="true" />
                <h3>{card.title}</h3>
                <p>{card.copy}</p>
              </article>
            );
          })}
        </div>
      </section>

      <section className="section two-column">
        <div className="section-heading">
          <h2>Docs, API, and contribution paths in one flow.</h2>
          <p>
            Start with product usage, move into architecture and endpoint contracts, then use the MCP
            tools to orient local development work.
          </p>
        </div>
        <div className="mcp-steps">
          {docsCards.map((item) => (
            <Link className="mcp-step" href={item.href} key={item.href}>
              <h3>{item.label}</h3>
              <p>{item.copy}</p>
            </Link>
          ))}
        </div>
      </section>

      <section className="section two-column">
        <div className="code-panel">
          <header>
            <span>Contributor MCP</span>
            <span>read-only</span>
          </header>
          <pre>{`{
  "mcpServers": {
    "flinttrade-docs": {
      "url": "https://<your-site>/api/mcp"
    },
    "flinttrade-local": {
      "command": "npm",
      "args": ["run", "mcp:stdio"],
      "cwd": "packages/apps/site"
    }
  }
}`}</pre>
        </div>
        <div className="section-heading">
          <h2>MCP for development, not trading.</h2>
          <p>
            The site exposes docs search, package maps, path explanations, test recommendations, and
            contribution prompts. Broker credentials, account state, funds, order IDs, and order placement
            stay outside this MCP surface.
          </p>
          <Link className="button secondary" href="/mcp">
            MCP setup <ArrowRight aria-hidden="true" size={17} />
          </Link>
        </div>
      </section>

      <section className="section">
        <div className="section-heading">
          <h2>Package map at contributor speed.</h2>
          <p>
            Each package README becomes a docs page and MCP resource, so agent-assisted development starts
            from the same public source a human contributor reads.
          </p>
        </div>
        <div className="package-list">
          {packages.map((pkg) => (
            <Link className="package-row" href={pkg.url} key={pkg.name}>
              <strong>{pkg.name}</strong>
              <span>{pkg.description}</span>
            </Link>
          ))}
        </div>
      </section>

      <SiteFooter />
    </main>
  );
}
