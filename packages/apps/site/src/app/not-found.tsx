import Link from 'next/link';

import { SiteHeader } from '@/components/site-header';
import { SiteFooter } from '@/components/site-footer';

export default function NotFound() {
  return (
    <div className="site-shell">
      <SiteHeader />
      <main className="subpage" id="site-content" tabIndex={-1}>
        <h1>Page not found</h1>
        <p>The page may have moved as the public docs site is generated from the repository docs.</p>
        <Link className="button primary" href="/docs">
          Open docs
        </Link>
      </main>
      <SiteFooter />
    </div>
  );
}
