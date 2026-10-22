import { readFileSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import DemoPage from '../app/demo/page';
import ExplorePage from '../app/explore/page';

function readSiteFile(relativePath: string): string {
  return readFileSync(path.resolve(process.cwd(), relativePath), 'utf8');
}

describe('site sandbox demo routing', () => {
  it('opens the generated terminal app directly instead of embedding it in an iframe', () => {
    const homePage = readSiteFile('src/app/page.tsx');
    const siteHeader = readSiteFile('src/components/site-header.tsx');
    const demoPage = readSiteFile('src/app/demo/page.tsx');
    const explorePage = readSiteFile('src/app/explore/page.tsx');

    expect(homePage).toContain('href="/demo-app/welcome"');
    expect(homePage).toContain('target="_blank"');
    expect(siteHeader).toContain("href: '/demo-app/welcome'");
    expect(siteHeader).toContain("target={item.newWindow ? '_blank' : undefined}");
    expect(demoPage).not.toContain('<iframe');
    expect(explorePage).not.toContain('<iframe');
  });

  it('permanently redirects /demo and /explore to the full-page demo', () => {
    const cases = [
      { source: readSiteFile('src/app/demo/page.tsx'), load: () => { DemoPage(); } },
      { source: readSiteFile('src/app/explore/page.tsx'), load: () => { ExplorePage(); } },
    ];

    for (const entry of cases) {
      // permanentRedirect() is Next's HTTP 308. redirect() is the temporary 307.
      expect(entry.source).toContain("from 'next/navigation'");
      expect(entry.source).toContain("permanentRedirect('/demo-app/welcome')");
      expect(entry.source).not.toContain("redirect('/demo-app/welcome')");

      let thrown: unknown;
      try {
        entry.load();
      } catch (error) {
        thrown = error;
      }
      expect(thrown).toMatchObject({
        digest: 'NEXT_REDIRECT;replace;/demo-app/welcome;308;',
      });
    }
  });

  it('keeps the demo app out of frames now that it launches as its own page', () => {
    const nextConfig = readSiteFile('next.config.mjs');

    expect(nextConfig).toContain("source: '/demo-app/:path*'");
    expect(nextConfig).toContain('"frame-ancestors \'none\'"');
  });
});
