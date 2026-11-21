import { ArrowRight, ExternalLink } from 'lucide-react';
import Link from 'next/link';
import Image from 'next/image';

/** Static post-intro composition. No market quotes or unqualified screenshot. */
export function ProductIntroduction({ entry = 'explore' }: { entry?: 'explore' | 'app' }) {
  return <section className="section product-introduction" aria-labelledby="workspace-heading">
    <p className="product-eyebrow">FlintTrade · self-hosted workspace</p>
    <h1 id="workspace-heading">Your market workspace.<br /><span>Your rules.</span></h1>
    <p className="product-introduction-copy">Research, practise and review Indian markets. Choose a layout, explore with example data, then decide what to install.</p>
    <div className="product-entry-actions">
      {entry === 'app'
        ? <a className="button primary" href="/demo-app/terminal">Choose a layout <ArrowRight size={18} aria-hidden="true" /></a>
        : <Link className="button primary" href="/explore">Explore the workspace <ArrowRight size={18} aria-hidden="true" /></Link>}
      <Link className="button secondary" href="/download">Install the web app</Link>
    </div>
    <figure className="product-monitor">
      <div className="product-monitor-screen"><Image src="/product/trading.webp" width={1280} height={800} sizes="(max-width: 768px) 94vw, 1080px" alt="Trading workspace with frozen example data, no connected broker or real orders" /></div>
      <div className="product-monitor-stand" aria-hidden="true" />
      <figcaption>Trading workspace · frozen example data, not live market data or trading performance. No broker is connected and no orders are sent.</figcaption>
    </figure>
    <div className="workspace-entry-grid" aria-label="Explore FlintTrade workspaces">
      <a href="/demo-app/terminal" target="_blank" rel="noopener noreferrer"><span className="entry-number">01 / TRADING</span><strong>Choose your layout.</strong><span>Charts, watchlists and account books. Save a layout without changing permissions.</span><em>Open Trading · example data <ExternalLink size={16} aria-hidden="true" /></em></a>
      <a href="/demo-app/testing" target="_blank" rel="noopener noreferrer"><span className="entry-number">02 / STUDIO</span><strong>Give ideas room.</strong><span>Explore strategy configuration before a run. No provider connection is required to look around.</span><em>Open Studio · example data <ExternalLink size={16} aria-hidden="true" /></em></a>
      <a href="/demo-app/reports" target="_blank" rel="noopener noreferrer"><span className="entry-number">03 / REVIEW</span><strong>Keep the evidence.</strong><span>Inspect example trade history and fees, separate from live outcomes.</span><em>Open Review · example data <ExternalLink size={16} aria-hidden="true" /></em></a>
    </div>
    <p className="product-example-note">Example data only. No broker is connected and no orders are sent. Explore the public demo before setting up your own workspace.</p>
  </section>;
}
