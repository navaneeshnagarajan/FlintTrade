/**
 * FT-SITE-001: marketing primary nav must stay usable on narrow phones.
 * Source-based contract (site Vitest is Node, no layout engine).
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

function readSite(relativePath: string): string {
  return readFileSync(resolve(process.cwd(), relativePath), 'utf8');
}

function mediaBlock(css: string, query: string, nextQuery?: string): string {
  const start = css.indexOf(`@media (${query})`);
  expect(start).toBeGreaterThan(-1);
  const fromQuery = css.slice(start);
  if (!nextQuery) {
    return fromQuery;
  }
  const next = fromQuery.indexOf(`@media (${nextQuery})`, 1);
  return next === -1 ? fromQuery : fromQuery.slice(0, next);
}

function rule(css: string, selector: string): string {
  const match = css.match(new RegExp(`${selector}\\s*\\{[^}]+\\}`));
  return match?.[0] ?? '';
}

describe('marketing primary nav (FT-SITE-001)', () => {
  const header = readSite('src/components/site-header.tsx');
  const css = readSite('src/app/globals.css');

  it('keeps every primary destination, including Contribute, in the header', () => {
    const required = [
      { href: '/download', label: 'Download' },
      { href: '/demo-app/welcome', label: 'Explore demo' },
      { href: '/docs', label: 'Docs' },
      { href: '/api-reference', label: 'API' },
      { href: '/mcp', label: 'MCP' },
      { href: '/contribute', label: 'Contribute' },
    ];

    for (const item of required) {
      expect(header).toContain(`href: '${item.href}'`);
      expect(header).toContain(`label: '${item.label}'`);
    }
  });

  it('does not clip nav labels behind overflow-x at phone widths', () => {
    const tablet = mediaBlock(css, 'max-width: 900px', 'max-width: 620px');
    const mobileNav = rule(tablet, '\\.main-nav');

    expect(mobileNav).toMatch(/flex-wrap:\s*wrap/);
    expect(mobileNav).not.toMatch(/overflow-x:\s*auto/);
    expect(mobileNav).toMatch(/overflow:\s*visible/);
  });

  it('stops primary nav links shrinking so Contribute cannot be crushed', () => {
    const tablet = mediaBlock(css, 'max-width: 900px', 'max-width: 620px');
    const navLinks =
      rule(tablet, '\\.main-nav a') || rule(css, '\\.main-nav a');

    expect(navLinks).toMatch(/flex-shrink:\s*0/);
    expect(navLinks).toMatch(/white-space:\s*nowrap/);
  });
});
