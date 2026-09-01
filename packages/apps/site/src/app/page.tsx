import { BRAND_SLOGAN_SENTENCE, BRAND_SLOGAN_WORDS, BRAND_WORDMARK, LogoIcon } from '@flinttrade/design-system/brand';
import { ArrowRight, Bot, ExternalLink, ShieldCheck, TerminalSquare } from 'lucide-react';
import Image from 'next/image';
import Link from 'next/link';

import { HeroCinematic } from '@/components/hero-cinematic';
import { SiteFooter } from '@/components/site-footer';
import { SiteHeader } from '@/components/site-header';
import { listPackages } from '@/lib/mcp/capabilities';
import { flinttradeAsset } from '@/lib/site-assets';
import { hostedMcpUrl, resolveSiteOrigin } from '@/lib/site-origin';

const featureCards = [
  {
    icon: TerminalSquare,
    title: 'A self-hosted workflow workspace',
    copy: 'React, FlexLayout, Python services, Rust tick processing, the OpenAlgo-compatible bridge, and evidence-gated native broker contracts in one inspectable workspace.',
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
  {
    href: '/download',
    label: 'Install',
    copy: 'Install the self-hosted web app in one line. Electron installers stay withheld until a checksummed release exists.',
  },
  { href: '/docs/user-guide', label: 'User Guide', copy: 'Install, connect OpenAlgo or verified native brokers, explore Practice mode, and learn the workspace.' },
  { href: '/docs/developer-guide', label: 'Developer Guide', copy: 'Repo map, tests, coding style, widgets, strategies, and PR flow.' },
  { href: '/docs/disclaimer', label: 'Beta Disclaimer', copy: 'Not production ready, no financial advice, and Live-mode risk notes.' },
  { href: '/api-reference', label: 'API Reference', copy: 'FlintTrade endpoints, auth, WebSocket contracts, and OpenAlgo bridge routes.' },
];

const wordmarkChars = BRAND_WORDMARK.split('');

// Same six-word slogan cascade as the terminal WelcomeRoute, imported from
// the design-system brand copy (the single source of truth). Colours and
// stagger delays live in globals.css (nth-child) — the site CSP blocks
// server-rendered style attributes, so styling must come from stylesheets.
// The nth-child colour rules stay valid because the word order is preserved.
const sloganWords = BRAND_SLOGAN_WORDS;

// Same four feature chips as the terminal welcome screen.
const welcomeFeatures = [
  'OpenAlgo bridge plus verified native brokers',
  'Explore, Practice, and Live safety modes',
  'Option chain, Greeks, order flow, and depth',
  'Strategy lab, SIP tracking, and AI context',
] as const;

// Byte-identical to the primary commands on /download. Do not point these at
// /install.sh or /install.ps1 — those are the gated Electron shell scripts.
const webInstallCommands = [
  {
    platform: 'macOS / Linux',
    command: 'curl -fsSL https://flinttrade.vercel.app/web-install.sh | bash',
  },
  {
    platform: 'Windows 10/11',
    command: 'irm https://flinttrade.vercel.app/web-install.ps1 | iex',
  },
] as const;

// Eight debris particles; offsets/delays are nth-child CSS in globals.css.
const impactDebris = Array.from({ length: 8 }, (_, i) => i);

export default async function HomePage() {
  const packages = listPackages().slice(0, 8);
  const mcpUrl = hostedMcpUrl(await resolveSiteOrigin());

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
          <h1 aria-label={BRAND_WORDMARK}>
            {wordmarkChars.map((char, index) => (
              <span aria-hidden="true" className="hero-title-char" key={`${char}-${index}`}>
                {char}
              </span>
            ))}
          </h1>
          <p className="sr-only">{BRAND_SLOGAN_SENTENCE}</p>
          <div className="hero-slogan" aria-hidden="true">
            {sloganWords.map((word, index) => (
              <span key={word}>
                {word}
                {index < sloganWords.length - 1 && <span className="slogan-dot">.</span>}
              </span>
            ))}
          </div>
          <p>
            Open-source self-hosted trading software for local research, sample-data
            testing, manual orders, automation, and AI-assisted workflows. It runs in
            the browser from your own machine. A desktop shell comes after a checksummed
            Electron release.
          </p>
          <p className="hero-disclaimer">
            v0.0.1 is not production ready. Use Explore and Practice modes first; Live mode remains your own risk.
          </p>
          <div className="hero-feature-grid">
            {welcomeFeatures.map((item) => (
              <div key={item}>{item}</div>
            ))}
          </div>
          <div className="hero-install" aria-labelledby="hero-web-install">
            <p id="hero-web-install">Install the self-hosted web app. Nothing else needs to be installed first.</p>
            {webInstallCommands.map((entry) => (
              <div className="code-panel" key={entry.platform}>
                <header>
                  <span>{entry.platform}</span>
                  <span>terminal</span>
                </header>
                <pre>
                  <code>{entry.command}</code>
                </pre>
              </div>
            ))}
          </div>
          <div className="hero-actions">
            <Link
              className="button primary"
              href="/download"
              aria-label="Open the FlintTrade web-app install page"
            >
              Install the web app <TerminalSquare aria-hidden="true" size={17} />
            </Link>
            <Link
              className="button secondary"
              href="/demo-app/welcome"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Start exploring the FlintTrade marketing demo in a new window"
            >
              Explore demo <ExternalLink aria-hidden="true" size={17} />
            </Link>
          </div>
          <p className="hero-electron-note">
            Electron installer pending.{' '}
            <Link href="/docs/desktop">Desktop guide</Link>
          </p>
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
            <span>Native broker contract and routing are safety-gated; adapters stay behind credential, ACL, and SDK checks.</span>
          </div>
          <div>
            <strong>18</strong>
            <span>Package surfaces across Python, React, shared UI, Rust/PyO3, and the Electron desktop shell.</span>
          </div>
          <div>
            <strong>71</strong>
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
      "url": "${mcpUrl}"
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
