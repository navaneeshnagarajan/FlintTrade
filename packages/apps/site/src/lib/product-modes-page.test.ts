/**
 * The product modes page is generated with the other docs and listed in the
 * docs navigation. /product-modes opens that same generated page.
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

const siteRoot = process.cwd();

function readSite(relativePath: string): string {
  return readFileSync(resolve(siteRoot, relativePath), 'utf8');
}

describe('product modes docs page', () => {
  it('generates the page and lists it in the docs navigation', () => {
    const generator = readSite('scripts/generate-content.mjs');
    expect(generator).toContain("['docs/product-modes.mdx', 'product-modes'");

    const meta = JSON.parse(readSite('content/docs/meta.json')) as { pages: string[] };
    expect(meta.pages).toContain('product-modes');

    const page = readSite('content/docs/product-modes.mdx');
    expect(page).toContain('The Mode chip in the TopBar is taken from the JWT `mode` claim');
    expect(page).toContain('**Unavailable** means the session mode could not be confirmed');
    expect(page).toContain('**Connected (read)** is a broker status');
  });

  it('opens /product-modes on the generated docs page', () => {
    const config = readSite('next.config.mjs');
    expect(config).toContain("source: '/product-modes'");
    expect(config).toContain("destination: '/docs/product-modes'");
  });
});
