import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import { shouldRenderDocsDescription } from './docs-description';

const SITE_ROOT = resolve(process.cwd());

function readSite(relativePath: string): string {
  return readFileSync(join(SITE_ROOT, relativePath), 'utf8');
}

function parseFrontmatter(content: string): Record<string, string> {
  const match = content.match(/^---\s*([\s\S]*?)\s*---/);
  if (!match) return {};
  const fm: Record<string, string> = {};
  for (const line of match[1].split('\n')) {
    const kv = line.match(/^\s*([a-zA-Z0-9_.-]+)\s*:\s*(.+?)\s*$/);
    if (kv) {
      fm[kv[1].trim()] = kv[2].trim().replace(/^["']|["']$/g, '');
    }
  }
  return fm;
}

function bodyAfterFrontmatter(content: string): string {
  return content.replace(/^---[\s\S]*?---\s*/, '');
}

describe('shouldRenderDocsDescription', () => {
  it('fails closed unless hideDescription is explicitly false', () => {
    expect(shouldRenderDocsDescription({ description: 'Welcome to FlintTrade', hideDescription: true })).toBe(
      false,
    );
    expect(shouldRenderDocsDescription({ description: 'Welcome to FlintTrade' })).toBe(false);
    expect(
      shouldRenderDocsDescription({
        description: 'Project documentation index',
        hideDescription: false,
      }),
    ).toBe(true);
  });
});

describe('docs summary dedupe wiring', () => {
  it('imports the shared description helper from the site generator', () => {
    const generator = readSite('scripts/generate-content.mjs');

    expect(generator).toContain("from './docs-description.mjs'");
    expect(generator).toContain('shouldHidePageDescription');
    expect(generator).toContain('hideDescription');
  });

  it('skips DocsDescription unless the page opts in with hideDescription false', () => {
    const page = readSite('src/app/docs/[[...slug]]/page.tsx');

    expect(page).toContain('shouldRenderDocsDescription');
    expect(page).toContain('DocsDescription');
    expect(page).toContain('page.data.hideDescription');
  });

  it('declares hideDescription on the Fumadocs frontmatter schema', () => {
    const config = readSite('source.config.ts');

    expect(config).toContain('frontmatterSchema');
    expect(config).toContain('hideDescription');
  });
});

describe('generated docs pages do not repeat the summary as the first body paragraph', () => {
  it('hides DocsDescription on the docs index whose description is the welcome paragraph', () => {
    const generated = readSite('content/docs/index.mdx');
    const fm = parseFrontmatter(generated);
    const body = bodyAfterFrontmatter(generated);

    expect(fm.description.startsWith('Welcome to the FlintTrade documentation.')).toBe(true);
    expect(fm.hideDescription).toBe('true');
    expect(body).toContain('Welcome to the FlintTrade documentation.');
    expect(body.startsWith('---')).toBe(false);
  });

  it('keeps a distinct MCP subtitle visible', () => {
    const generated = readSite('content/docs/mcp.mdx');
    const fm = parseFrontmatter(generated);
    const body = bodyAfterFrontmatter(generated);

    expect(fm.description).toBe(
      'Read-only MCP surfaces for development, documentation, and contribution workflows.',
    );
    expect(fm.hideDescription).toBe('false');
    expect(body.startsWith('The FlintTrade docs MCP is a read-only development assistant.')).toBe(true);
    expect(body).not.toContain(fm.description);
  });
});
