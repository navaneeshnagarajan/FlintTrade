import { BRAND_SLOGAN_SENTENCE, BRAND_SLOGAN_WORDS, BRAND_WORDMARK, LogoIcon } from '@flinttrade/design-system/brand';
import { ArrowRight, ExternalLink, TerminalSquare } from 'lucide-react';
import Link from 'next/link';

import { HeroCinematic } from '@/components/hero-cinematic';
import { ProductOverview } from '@/components/product-overview';
import SiteScrollWorld from '@/components/site-scroll-world';
import { SiteFooter } from '@/components/site-footer';
import { SiteHeader } from '@/components/site-header';
import { hostedMcpUrl, resolveSiteOrigin } from '@/lib/site-origin';
import { webInstallCommands } from '@/lib/web-install-commands';

const wordmarkChars = BRAND_WORDMARK.split('');

// Same six-word slogan cascade as the terminal WelcomeRoute, imported from
// the design-system brand copy (the single source of truth). Colours and
// stagger delays live in globals.css (nth-child) — the site CSP blocks
// server-rendered style attributes, so styling must come from stylesheets.
// The nth-child colour rules stay valid because the word order is preserved.
const sloganWords = BRAND_SLOGAN_WORDS;

// Same four feature chips as the terminal welcome screen.
const welcomeFeatures = [
  'Six native adapters with evidence-gated availability',
  'Practice, Connected (read), and Live',
  'Option chain, Greeks, order flow, and depth',
  'Strategy lab, SIP tracking, and AI context',
] as const;

// Eight debris particles; offsets/delays are nth-child CSS in globals.css.
const impactDebris = Array.from({ length: 8 }, (_, i) => i);

export default async function HomePage() {
  const origin = await resolveSiteOrigin();
  const mcpUrl = hostedMcpUrl(origin);
  const WEB_INSTALL_COMMANDS = webInstallCommands(origin);

  return (
    <div className="site-shell product-site">
      <div className="site-cinematic-backdrop" aria-hidden="true">
        <HeroCinematic />
        <SiteScrollWorld />
      </div>
      <SiteHeader />
      <main id="site-content" tabIndex={-1}>

      <section className="section hero" data-scroll-chapter="0">
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
            Research, practise and review Indian markets. A self-hosted trading workspace for people and AI, with explicit execution permissions.
          </p>
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
              aria-label="Open Demo (example data) in a new window"
            >
              Demo (example data) <ExternalLink aria-hidden="true" size={17} />
            </Link>
          </div>
        </div>
      </section>

      <aside className="product-notice" aria-label="Software status">
        <p>v0.0.1 is not production ready. Use Practice and example data first; Live mode remains your own risk.</p>
        <Link href="/docs/disclaimer">Read the disclaimer <ArrowRight size={16} aria-hidden="true" /></Link>
      </aside>

      <ProductOverview />

      <section className="section product-section permission-section" aria-labelledby="permissions-heading">
        <header className="product-heading">
          <h2 id="permissions-heading">Choose the mode. Keep the limits.</h2>
          <p>Example data is not a Mode. Connection status, account permissions and execution mode remain separate decisions.</p>
        </header>
        <dl className="mode-list">
          <div>
            <dt>Practice</dt>
            <dd>Work with simulated fills. Practice results are not live execution evidence.</dd>
          </div>
          <div>
            <dt>Connected (read)</dt>
            <dd>Read broker data where available. A connection does not grant permission to place orders.</dd>
          </div>
          <div>
            <dt>Live</dt>
            <dd>Real orders require explicit permissions and supported account capabilities. Automation is not enabled by opening the app.</dd>
          </div>
        </dl>
        <p className="product-note">Native broker connections are currently unavailable. Start with Practice and review the setup requirements before connecting an account.</p>
        <details className="availability-details">
          <summary>Capability and connection availability</summary>
          <ul>{welcomeFeatures.map((feature) => <li key={feature}>{feature}</li>)}</ul>
          <p><strong>71</strong> widgets are listed in the contributor catalogue. Availability depends on configuration and data sources.</p>
          <p>Broker connections use the native gateway. Native connections remain frozen. Native broker HTTP is frozen until Task 9D and Task 7C.2; adapters stay evidence-gated behind credential, ACL, and SDK checks.</p>
          <Link href="/docs/user-guide">Read the current setup requirements</Link>
        </details>
      </section>

      <section className="section product-section install-section" aria-labelledby="web-app-install">
        <header className="product-heading">
          <h2 id="web-app-install">Run it on your own machine.</h2>
          <p>Install the self-hosted web app, then start with Practice. Review the install instructions and scripts before running a command.</p>
        </header>
        <div className="install-commands">
          {WEB_INSTALL_COMMANDS.map((entry) => (
            <div className="code-panel" key={entry.platform}>
              <header><span>{entry.platform}</span><span>Web app</span></header>
              <pre tabIndex={0} aria-label={`${entry.platform} web-app install command`}><code>{entry.command}</code></pre>
            </div>
          ))}
        </div>
        <div className="product-links">
          <Link href="/download">Install the web app <ArrowRight size={16} aria-hidden="true" /></Link>
          <Link href="/docs/desktop">Desktop guide <ArrowRight size={16} aria-hidden="true" /></Link>
        </div>
        <p className="product-note">Electron installer pending. Desktop downloads stay withheld until a complete, checksummed release is available.</p>
        <p className="product-note">If a hosted command is unavailable, the install page includes repository-direct alternatives and uninstall instructions.</p>
      </section>

      <section className="section product-section contributor-section" aria-labelledby="contributor-heading" data-scroll-chapter="4">
        <header className="product-heading">
          <h2 id="contributor-heading">Open source. Open to inspection.</h2>
          <p>Read the product guides, inspect the API contracts or contribute a change. The public documentation comes from the repository.</p>
        </header>
        <nav className="resource-links" aria-label="Product and contributor resources">
          <Link href="/docs/user-guide">User guide <ArrowRight size={16} aria-hidden="true" /></Link>
          <Link href="/docs/developer-guide">Developer guide <ArrowRight size={16} aria-hidden="true" /></Link>
          <Link href="/api-reference">API reference <ArrowRight size={16} aria-hidden="true" /></Link>
          <Link href="/mcp">Contributor MCP <ArrowRight size={16} aria-hidden="true" /></Link>
          <Link href="/contribute">Contribute <ArrowRight size={16} aria-hidden="true" /></Link>
        </nav>
        <p className="product-note">MCP for development, not trading. The public MCP is read-only: it does not expose broker credentials, account state or order placement.</p>
        <p className="product-note">Read-only docs endpoint: <code className="mcp-endpoint">{mcpUrl}</code></p>
      </section>

      </main>
      <div data-scroll-chapter="5">
        <SiteFooter />
      </div>
    </div>
  );
}
