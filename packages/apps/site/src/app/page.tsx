import { LogoIcon } from '@flinttrade/design-system/brand';
import { ArrowRight, Bot, Cable, PlayCircle, ShieldCheck, TerminalSquare } from 'lucide-react';
import Image from 'next/image';
import Link from 'next/link';

import { HeroCinematic } from '@/components/hero-cinematic';
import { SiteFooter } from '@/components/site-footer';
import { SiteHeader } from '@/components/site-header';
import { listPackages } from '@/lib/mcp/capabilities';
import { flinttradeAsset } from '@/lib/site-assets';

const featureCards = [
  {
    icon: TerminalSquare,
    title: 'A self-hosted workflow workspace',
    copy: 'React, Dockview, Python services, Rust tick processing, a native broker gateway contract, and optional OpenAlgo integration in one inspectable workspace.',
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
  { href: '/docs/user-guide', label: 'User Guide', copy: 'Install, connect optional integrations, explore Practice mode, and learn the workspace.' },
  { href: '/docs/developer-guide', label: 'Developer Guide', copy: 'Repo map, tests, coding style, widgets, strategies, and PR flow.' },
  { href: '/docs/disclaimer', label: 'Alpha Disclaimer', copy: 'Not production ready, no financial advice, and Live-mode risk notes.' },
  { href: '/api-reference', label: 'API Reference', copy: 'FlintTrade endpoints, auth, WebSocket contracts, and optional OpenAlgo passthrough.' },
];

const wordmarkChars = 'FlintTrade'.split('');

// Same six-word slogan cascade as the terminal WelcomeRoute. Colours and
// stagger delays live in globals.css (nth-child) — the site CSP blocks
// server-rendered style attributes, so styling must come from stylesheets.
const sloganWords = ['Inspect', 'Build', 'Test', 'Automate', 'Analyse', 'Evolve'] as const;

// Same four feature chips as the terminal welcome screen.
const welcomeFeatures = [
  'Native broker gateway plus optional OpenAlgo bridge',
  'Explore, Practice, and Live safety modes',
  'Option chain, Greeks, order flow, and depth',
  'Strategy lab, SIP tracking, and AI context',
] as const;

// Eight debris particles; offsets/delays are nth-child CSS in globals.css.
const impactDebris = Array.from({ length: 8 }, (_, i) => i);

export default function HomePage() {
  const packages = listPackages().slice(0, 8);

  return (
    <main className="site-shell">
      <div className="site-cinematic-backdrop" aria-hidden="true">
        <HeroCinematic />
      </div>
      <SiteHeader />

      <section className="section hero">
        <div className="hero-copy">
          <div className="hero-logo-stage" aria-hidden="true">
            <span className="site-hero-fireball" />
            <span className="site-impact-blast" />
            <span className="site-shock-ring" />
            <span className="site-shock-ring site-shock-ring-secondary" />
            {impactDebris.map((index) => (
              <span className="site-impact-debris" key={index} />
            ))}
            <div className="hero-logo-mark hero-logo-reveal">
              <LogoIcon size={86} aria-hidden="true" />
            </div>
          </div>
          <h1 aria-label="FlintTrade">
            {wordmarkChars.map((char, index) => (
              <span aria-hidden="true" className="hero-title-char" key={`${char}-${index}`}>
                {char}
              </span>
            ))}
          </h1>
          <p className="sr-only">Inspect. Build. Test. Automate. Analyse. Evolve.</p>
          <div className="hero-slogan" aria-hidden="true">
            {sloganWords.map((word, index) => (
              <span key={word}>
                {word}
                {index < sloganWords.length - 1 && <span className="slogan-dot">.</span>}
              </span>
            ))}
          </div>
          <p>
            Open-source self-hosted market workflow software for local research, sandbox
            testing, automation, and AI diagnostics. One native app for macOS, Windows,
            and Linux.
          </p>
          <p className="hero-disclaimer">
            v0.6.0-beta is not production ready. Use Explore and Practice modes first; Live mode remains your own risk.
          </p>
          <div className="hero-feature-grid">
            {welcomeFeatures.map((item) => (
              <div key={item}>{item}</div>
            ))}
          </div>
          <div className="hero-actions">
            <Link className="button shimmer" href="/demo">
              Open the Explore demo <PlayCircle aria-hidden="true" size={17} />
            </Link>
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
              <Image src={flinttradeAsset('screenshots/01-welcome.png')} alt="FlintTrade cinematic welcome screen" fill priority sizes="(max-width: 900px) 100vw, 58vw" />
            </figure>
            <figure className="screen-frame side">
              <Image src={flinttradeAsset('screenshots/04-trade.png')} alt="FlintTrade trade canvas" fill sizes="(max-width: 900px) 46vw, 22vw" />
            </figure>
            <figure className="screen-frame float">
              <Image src={flinttradeAsset('screenshots/06-lab.png')} alt="Strategy lab" fill sizes="(max-width: 900px) 42vw, 20vw" />
            </figure>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="metric-rail" aria-label="Project facts">
          <div>
            <strong>Gateway</strong>
            <span>Native broker contract and routing are scaffolded; Dhan direct adapter is gated pending SDK attestation.</span>
          </div>
          <div>
            <strong>17</strong>
            <span>Package surfaces across Python, React, shared UI, and Rust/PyO3.</span>
          </div>
          <div>
            <strong>95</strong>
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
