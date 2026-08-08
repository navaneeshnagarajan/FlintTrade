/**
 * docs.page pilot publication guards (RED then GREEN).
 * Mechanically asserts the bounded pilot artifacts without snapshots or tautologies.
 * Fails in RED because required files are absent.
 */

import { readFileSync, existsSync, readdirSync } from 'node:fs';
import { join, resolve, relative, sep } from 'node:path';

import { describe, expect, it } from 'vitest';

const REPO_ROOT = resolve(process.cwd(), '..', '..', '..');
const DOCS_DIR = resolve(REPO_ROOT, 'docs');
const DOCS_JSON = resolve(REPO_ROOT, 'docs.json');

const PILOT_ROUTES = ['/', '/getting-started', '/product-modes', '/safety', '/contributing'] as const;
const PILOT_MDX_FILES = [
  'index.mdx',
  'getting-started.mdx',
  'product-modes.mdx',
  'safety.mdx',
  'contributing.mdx',
] as const;

function parseFrontmatter(content: string): Record<string, string> {
  const match = content.match(/^---\s*([\s\S]*?)\s*---/);
  if (!match) return {};
  const fm: Record<string, string> = {};
  const lines = match[1].split('\n');
  for (const line of lines) {
    const kv = line.match(/^\s*([a-zA-Z0-9_.-]+)\s*:\s*(.+?)\s*$/);
    if (kv) {
      fm[kv[1].trim()] = kv[2].trim().replace(/^["']|["']$/g, '');
    }
  }
  return fm;
}

function listMdxFiles(dir: string): string[] {
  const results: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...listMdxFiles(fullPath));
    } else if (entry.name.endsWith('.mdx')) {
      results.push(fullPath);
    }
  }
  return results;
}

describe('docs.page pilot publication guards', () => {
  it('root docs.json parses as JSON', () => {
    expect(existsSync(DOCS_JSON)).toBe(true);
    const raw = readFileSync(DOCS_JSON, 'utf8');
    const parsed = JSON.parse(raw);
    expect(parsed).toBeTypeOf('object');
  });

  it('docs.json declares correct schema, seo.noindex, mcp.enabled, logos, and infer setting', () => {
    const parsed = JSON.parse(readFileSync(DOCS_JSON, 'utf8'));
    expect(parsed.$schema).toBe('https://docs.page/schema.json');
    expect(parsed.seo?.noindex).toBe(true);
    expect(parsed.mcp?.enabled).toBe(true);
    expect(parsed.logo?.light).toBe('/docs/assets/logo.svg');
    expect(parsed.logo?.dark).toBe('/docs/assets/logo.svg');
    expect(parsed.content?.automaticallyInferNextPrevious).toBe(true);
  });

  it('docs.json has no agent, scripts, or DocSearch config', () => {
    const parsed = JSON.parse(readFileSync(DOCS_JSON, 'utf8'));
    expect(parsed.agent).toBeUndefined();
    expect(parsed.scripts).toBeUndefined();
    expect(parsed.search?.docsearch).toBeUndefined();
  });

  it('docs.json sidebar exactly matches the five pilot routes', () => {
    const parsed = JSON.parse(readFileSync(DOCS_JSON, 'utf8'));
    const sidebar = parsed.sidebar || [];
    const routes = sidebar.map((item: any) => item.href || item.route || item.path).filter(Boolean);
    expect(routes).toEqual(expect.arrayContaining(PILOT_ROUTES));
    expect(routes.length).toBe(PILOT_ROUTES.length);
  });

  it('exactly the five pilot MDX files exist and no others in docs/', () => {
    expect(existsSync(DOCS_DIR)).toBe(true);
    const mdxFiles = listMdxFiles(DOCS_DIR);
    const basenames = mdxFiles.map((f) => relative(DOCS_DIR, f).split(sep).join('/')).sort();
    expect(basenames).toEqual(PILOT_MDX_FILES.sort());
  });

  it('every pilot page has non-empty title and description frontmatter', () => {
    for (const fname of PILOT_MDX_FILES) {
      const full = join(DOCS_DIR, fname);
      expect(existsSync(full)).toBe(true);
      const content = readFileSync(full, 'utf8');
      const fm = parseFrontmatter(content);
      expect(fm.title).toBeTruthy();
      expect(fm.description).toBeTruthy();
    }
  });

  it('canonical mode/surface/provenance language is represented; retired labels not presented as current', () => {
    const allContent = PILOT_MDX_FILES.map((f) => readFileSync(join(DOCS_DIR, f), 'utf8')).join('\n');
    expect(allContent).toContain('Explore');
    expect(allContent).toContain('Practice');
    expect(allContent).toContain('Live');
    expect(allContent).toContain('Sample');
    expect(allContent).toContain('Home');
    expect(allContent).toContain('Trade');
    // Retired first-class labels should not appear as current modes
    expect(allContent).not.toMatch(/\bDemo\b/i);
    expect(allContent).not.toMatch(/\bSandbox\b/i);
    expect(allContent).not.toMatch(/\bPaper\b/i);
  });

  it('every sidebar route resolves to the exact MDX file', () => {
    const parsed = JSON.parse(readFileSync(DOCS_JSON, 'utf8'));
    const sidebar = parsed.sidebar || [];
    for (const item of sidebar) {
      const href = item.href || item.route || item.path;
      if (!href) continue;
      const expectedFile = href === '/' ? 'index.mdx' : `${href.replace(/^\//, '')}.mdx`;
      const full = join(DOCS_DIR, expectedFile);
      expect(existsSync(full)).toBe(true);
    }
  });

  it('no pilot page links to an absent internal route or contains private paths/secrets', () => {
    const denied = ['.local/', 'reference-research', 'Nitro', '/private', 'machine-name', 'secret', 'token', 'key='];
    for (const fname of PILOT_MDX_FILES) {
      const content = readFileSync(join(DOCS_DIR, fname), 'utf8');
      for (const d of denied) {
        expect(content).not.toContain(d);
      }
      // Internal links must point to pilot routes
      const internalLinks = content.match(/\[.*?\]\(\/[^)]+\)/g) || [];
      for (const link of internalLinks) {
        const route = link.match(/\(\/([^)]+)\)/)?.[1] || '';
        if (route && !PILOT_ROUTES.includes(`/${route}` as any) && route !== '') {
          // allow only the five
          expect(PILOT_ROUTES).toContain(`/${route}`);
        }
      }
    }
  });

  it('config cannot silently enable Ask AI', () => {
    const parsed = JSON.parse(readFileSync(DOCS_JSON, 'utf8'));
    expect(parsed.agent).toBeUndefined();
    expect(parsed.askAI).toBeUndefined();
    expect(parsed.mcp?.ask).toBeUndefined();
  });
});
