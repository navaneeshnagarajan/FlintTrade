import type { Metadata } from 'next';
import Link from 'next/link';
import { ProductIntroduction } from '@/components/product-introduction';
import { SiteHeader } from '@/components/site-header';
import { SiteFooter } from '@/components/site-footer';

export const metadata: Metadata = {
  title: 'Explore the workspace',
  description: 'Choose a FlintTrade public-demo workspace, explore layouts with example data, and read the setup requirements.',
};

export default function ExplorePage() {
  return <div className="site-shell product-site">
    <SiteHeader activePath="/explore" />
    <main id="site-content" tabIndex={-1}>
      <ProductIntroduction entry="app" />
      <section className="section product-section" aria-labelledby="explore-next">
        <header className="product-heading"><h2 id="explore-next">From a first look to your own setup.</h2><p>The public demo is a frozen simulation, not a connected account. Layout selection and trading authority are separate.</p></header>
        <ol className="journey-steps">
          <li><strong>Explore with example data</strong><p>Open Trading, use the layout chooser and inspect the available panels. Public-demo values are not live prices or performance.</p><Link href="/demo-app/welcome" target="_blank" rel="noopener noreferrer">Start the demo (example data) ↗</Link></li>
          <li><strong>Read the requirements</strong><p>Review supported workflows and current availability before installing. Native broker connections remain unavailable.</p><Link href="/docs/user-guide">Read the user guide →</Link></li>
          <li><strong>Install, then practise</strong><p>Inspect the install scripts and choose your platform. Desktop downloads remain withheld until a complete verified release exists.</p><Link href="/download">Choose installation instructions →</Link></li>
        </ol>
        <div className="product-links"><Link href="/docs/disclaimer">Read the risk disclaimer →</Link><Link href="/docs/inventory">Inspect feature availability →</Link></div>
      </section>
    </main>
    <SiteFooter />
  </div>;
}
