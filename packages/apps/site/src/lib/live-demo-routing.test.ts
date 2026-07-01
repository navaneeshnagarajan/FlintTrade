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
    const demoPage = readSiteFile('src/app/demo/page.tsx');

    expect(homePage).toContain('href="/demo-app/welcome"');
    expect(homePage).toContain('target="_blank"');
    expect(siteHeader).toContain("href: '/demo-app/welcome'");
    expect(siteHeader).toContain("target={item.newWindow ? '_blank' : undefined}");
    expect(demoPage).toContain("redirect('/demo-app/welcome')");
    expect(demoPage).not.toContain('<iframe');
  });

  it('keeps the demo app out of frames now that it launches as its own page', () => {
    const nextConfig = readSiteFile('next.config.mjs');

    expect(nextConfig).toContain("source: '/demo-app/:path*'");
    expect(nextConfig).toContain('"frame-ancestors \'none\'"');
  });
});
