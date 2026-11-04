/**
 * Navigation presentation guards. Mounted disclosure, route and skip-link
 * behaviour is exercised by app/page.test.ts; viewport geometry needs browser acceptance.
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const header = readFileSync(resolve(process.cwd(), 'src/components/site-header.tsx'), 'utf8');
const presentation = readFileSync(resolve(process.cwd(), 'src/app/presentation.css'), 'utf8');
const layout = readFileSync(resolve(process.cwd(), 'src/app/layout.tsx'), 'utf8');

describe('marketing navigation', () => {
  it('keeps every primary destination, including Contribute, in the header', () => {
    const required = [
      { href: '/download', label: 'Download' },
      { href: '/demo-app/welcome', label: 'Demo (example data)' },
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

  it('loads the static presentation after the protected signature stylesheet', () => {
    expect(layout.indexOf("import './presentation.css'")).toBeGreaterThan(layout.indexOf("import './globals.css'"));
    expect(presentation).not.toMatch(/@keyframes|\b(?:animation|transition)\s*:/);
    expect(presentation).not.toMatch(/\.hero-logo|\.hero-title-char|\.hero-slogan|\.site-particles|\.site-impact/);
  });

  it('switches to the compact menu before desktop links can wrap', () => {
    const compact = presentation.slice(presentation.indexOf('@media (max-width: 1100px)'));
    expect(compact).toMatch(/\.site-header \.main-nav\s*\{\s*display:\s*none/);
    expect(compact).toMatch(/\.site-menu\s*\{\s*display:\s*block/);
    expect(compact).toContain('grid-template-columns: auto 1fr auto');
  });

  it('contains long compact navigation labels without clipping or horizontal scrolling', () => {
    expect(presentation).toMatch(/\.site-menu nav\s*\{[^}]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/);
    expect(presentation).toMatch(/\.site-menu nav a\s*\{[^}]*overflow-wrap:\s*anywhere/);
    // Only the hero may contain its off-viewport decoration. Navigation and
    // document rules must remain unclipped; real fireball geometry is browser-tested.
    const horizontalContainment = [...presentation.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
      .filter((rule) => /overflow-x:\s*(?:auto|hidden|clip)/.test(rule[2]))
      .map((rule) => rule[1].trim());
    expect(horizontalContainment).toEqual(['.product-site .hero']);
  });

  it('keeps visible keyboard focus treatment for links, buttons and the native disclosure', () => {
    expect(presentation).toContain(':where(a, button, summary, pre[tabindex]):focus-visible');
    expect(presentation).toContain('outline: 2px solid var(--site-accent)');
    expect(presentation).toContain('.site-skip-link:not(:focus)');
    expect(header).toContain('<summary>Menu</summary>');
  });
});
