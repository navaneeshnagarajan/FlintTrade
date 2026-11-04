import { ArrowRight, ExternalLink } from 'lucide-react';
import Image from 'next/image';
import Link from 'next/link';

/** Public-demo UI-fix snapshot views, not live market or performance evidence. */
export function ProductOverview() {
  return (
    <>
      <section className="section product-section" aria-labelledby="trading-heading" data-scroll-chapter="1">
        <header className="product-heading">
          <h2 id="trading-heading">Trading</h2>
          <p className="product-lead">The market and your account, together.</p>
          <p>Arrange charts, watchlists, option chains and account books around the way you work. Save a layout without changing trading permissions.</p>
        </header>
        <figure className="product-figure">
          <Image
            src="/product/trading.webp"
            alt="FlintTrade Trading market-watch layout with a chart, watchlist, positions and indices using example data"
            width={1600}
            height={900}
            sizes="(max-width: 768px) 100vw, 1180px"
          />
          <figcaption>Trading in the public demo with example data. Prices and results shown are not live market data or trading performance.</figcaption>
        </figure>
        <div className="product-links">
          <Link href="/demo-app/terminal" target="_blank" rel="noopener noreferrer">
            Trading demo (example data) <ExternalLink size={16} aria-hidden="true" />
          </Link>
          <Link href="/docs/user-guide">Read the user guide <ArrowRight size={16} aria-hidden="true" /></Link>
        </div>
      </section>

      <section className="section product-section studio-section" aria-labelledby="studio-heading" data-scroll-chapter="2">
        <div className="studio-copy">
          <header className="product-heading">
            <h2 id="studio-heading">Studio</h2>
            <p className="product-lead">Give an idea room to be tested.</p>
            <p>Research strategies, work with AI tools and inspect run evidence. Keep provider configuration separate from trading permissions.</p>
          </header>
          <div className="product-principle">
            <h3>A conversation is not trading permission.</h3>
            <p>AI needs a configured provider. Live execution needs explicit account permissions and qualification; opening a conversation grants neither.</p>
          </div>
          <div className="product-links">
            <Link href="/demo-app/testing" target="_blank" rel="noopener noreferrer">
              Studio demo (example data) <ExternalLink size={16} aria-hidden="true" />
            </Link>
          </div>
        </div>
        <figure className="product-figure">
          <Image
            src="/product/studio.webp"
            alt="FlintTrade Testing strategy research configuration before a run, using example data"
            width={1600}
            height={900}
            sizes="(max-width: 768px) 100vw, 720px"
          />
          <figcaption>Strategy research in Testing, before a run, with example data. Prices and results shown are not live market data or trading performance.</figcaption>
        </figure>
      </section>

      <section className="section product-section review-section" aria-labelledby="review-heading" data-scroll-chapter="3">
        <header className="product-heading">
          <h2 id="review-heading">Review</h2>
          <p className="product-lead">Keep the evidence beside the decision.</p>
          <p>Return to trade history, research results and your journal. Review what happened before deciding what to repeat.</p>
        </header>
        <figure className="product-figure">
          <Image
            src="/product/review.webp"
            alt="FlintTrade Reports trade-review log with fills, fees and outcomes using example data"
            width={1600}
            height={900}
            sizes="(max-width: 768px) 100vw, 1180px"
          />
          <figcaption>Trade review in Reports with example data. Prices and results shown are not live market data or trading performance.</figcaption>
        </figure>
        <dl className="review-topics">
          <div>
            <dt>Outcomes</dt>
            <dd>Read orders and fills in their account context. A submitted order is not a confirmed fill.</dd>
          </div>
          <div>
            <dt>Journal</dt>
            <dd>Record your reasoning and review it alongside the trade, not just the final number.</dd>
          </div>
          <div>
            <dt>Research evidence</dt>
            <dd>Keep simulated results separate from live outcomes. A backtest does not qualify an account.</dd>
          </div>
        </dl>
        <div className="product-links">
          <Link href="/demo-app/reports" target="_blank" rel="noopener noreferrer">
            Review demo (example data) <ExternalLink size={16} aria-hidden="true" />
          </Link>
        </div>
        <p className="product-note">The public demo uses example data. No broker is connected and no orders are sent.</p>
      </section>
    </>
  );
}
