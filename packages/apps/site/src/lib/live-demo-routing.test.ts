import { readFileSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

function readSiteFile(relativePath: string): string {
  return readFileSync(path.resolve(process.cwd(), relativePath), 'utf8');
}

describe('site sandbox demo routing', () => {
  it('opens the generated terminal app directly instead of embedding it in an iframe', () => {
    const homePage = readSiteFile('src/app/page.tsx');
    const siteHeader = readSiteFile('src/components/site-header.tsx');

    expect(homePage).toContain('href="/demo-app/welcome"');
    expect(homePage).toContain('target="_blank"');
    expect(siteHeader).toContain("href: '/demo-app/welcome'");
    expect(siteHeader).toContain("target={item.newWindow ? '_blank' : undefined}");
    expect(homePage).not.toContain('<iframe');
    expect(siteHeader).not.toContain('<iframe');
  });

  it('permanently redirects /demo and /explore from next.config', () => {
    const nextConfig = readSiteFile('next.config.mjs');

    for (const source of ["'/demo'", "'/explore'"]) {
      const entry = nextConfig.slice(nextConfig.indexOf(`source: ${source}`));
      expect(entry.startsWith(`source: ${source}`), source).toBe(true);
      expect(entry.slice(0, entry.indexOf('},'))).toContain("destination: '/demo-app/welcome'");
      expect(entry.slice(0, entry.indexOf('},'))).toContain('permanent: true');
    }
  });

  it('keeps the demo app out of frames now that it launches as its own page', () => {
    const nextConfig = readSiteFile('next.config.mjs');

    expect(nextConfig).toContain("source: '/demo-app/:path*'");
    expect(nextConfig).toContain('"frame-ancestors \'none\'"');
  });
});
