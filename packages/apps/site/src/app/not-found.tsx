import Link from 'next/link';

import { SiteHeader } from '@/components/site-header';

export default function NotFound() {
  return (
    <main className="site-shell">
      <SiteHeader />
      <section className="subpage">
        <h1>Page not found</h1>
        <p>The page may have moved as the public docs site is generated from the repository docs.</p>
        <Link className="button primary" href="/docs">
          Open docs
        </Link>
      </section>
    </main>
  );
}
