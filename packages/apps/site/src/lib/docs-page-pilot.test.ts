/**
 * docs.page pilot publication guards (RED then GREEN, CORRECTION-v1).
 * Mechanically asserts the bounded pilot artifacts without snapshots or tautologies.
 * Tests-only RED commit: tightens schema, sidebar shape, public links, provenance independence.
 * Fails in RED because current config/content violates the new strict guards.
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

  it('docs.json sidebar is official group object (non-flat) with exactly five canonical pages', () => {
    const parsed = JSON.parse(readFileSync(DOCS_JSON, 'utf8'));
    const sidebar = parsed.sidebar || [];
    expect(sidebar).toHaveLength(1);
    const groupItem = sidebar[0];
    expect(groupItem).toHaveProperty('group');
    expect(typeof groupItem.group).toBe('string');
    expect(groupItem.group.length).toBeGreaterThan(0);
    expect(groupItem).toHaveProperty('pages');
    expect(Array.isArray(groupItem.pages)).toBe(true);
    expect(groupItem.pages).toHaveLength(5);
    // reject flat {href, label} entries at top level of sidebar
    expect(sidebar.every((item: any) => !('label' in item && 'href' in item && !('group' in item || 'pages' in item)))).toBe(true);
    // exact pages in order
    const expectedPages = [
      { title: 'Home', href: '/' },
      { title: 'Getting Started', href: '/getting-started' },
      { title: 'Product Modes', href: '/product-modes' },
      { title: 'Safety', href: '/safety' },
      { title: 'Contributing', href: '/contributing' },
    ];
    expect(groupItem.pages).toEqual(expectedPages);
  });

  it('docs.json requires social.github exact public origin and forbids top-level github', () => {
    const parsed = JSON.parse(readFileSync(DOCS_JSON, 'utf8'));
    expect(parsed.github).toBeUndefined();
    expect(parsed.social?.github).toBe('https://github.com/navaneeshnagarajan/FlintTrade');
  });

  it('docs.json recursively forbids agent, scripts, docsearch, analytics, token, key', () => {
    const parsed = JSON.parse(readFileSync(DOCS_JSON, 'utf8'));
    const jsonStr = JSON.stringify(parsed);
    expect(jsonStr).not.toContain('"agent"');
    expect(jsonStr).not.toContain('"scripts"');
    expect(jsonStr).not.toContain('docsearch');
    expect(jsonStr).not.toContain('analytics');
    expect(jsonStr).not.toContain('token');
    expect(jsonStr).not.toContain('key=');
  });

  it('exactly the five pilot MDX files exist and no others in docs/', () => {
    expect(existsSync(DOCS_DIR)).toBe(true);
    const mdxFiles = listMdxFiles(DOCS_DIR);
    const basenames = mdxFiles.map((f) => relative(DOCS_DIR, f).split(sep).join('/')).sort();
    expect(basenames).toEqual([...PILOT_MDX_FILES].sort());
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
    // also check group pages
    if (sidebar[0]?.pages) {
      for (const p of sidebar[0].pages) {
        const href = p.href;
        if (!href) continue;
        const expectedFile = href === '/' ? 'index.mdx' : `${href.replace(/^\//, '')}.mdx`;
        const full = join(DOCS_DIR, expectedFile);
        expect(existsSync(full)).toBe(true);
      }
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

  it('every external pilot link uses exact public origin and rejects wrong flinttrade repo', () => {
    const correctOrigin = 'https://github.com/navaneeshnagarajan/FlintTrade';
    const wrongOrigin = 'https://github.com/flinttrade/flinttrade';
    for (const fname of PILOT_MDX_FILES) {
      const content = readFileSync(join(DOCS_DIR, fname), 'utf8');
      // reject any wrong repo URL
      expect(content).not.toContain(wrongOrigin);
      // external https links to github must be the correct one (if any github links present)
      const githubLinks = content.match(/https:\/\/github\.com\/[^)\s"']+/g) || [];
      for (const link of githubLinks) {
        expect(link.startsWith(correctOrigin)).toBe(true);
      }
    }
  });

  it('requires exact canonical public links for README, setup, developer, CI, ORDER_SAFETY, disclaimer (no placeholders)', () => {
    const allContent = PILOT_MDX_FILES.map((f) => readFileSync(join(DOCS_DIR, f), 'utf8')).join('\n');
    const required = [
      'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/readme.md',
      'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/docs/setup/QUICKSTART.md',
      'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/docs/DEVELOPER_GUIDE.md',
      'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/docs/CI.md',
      'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/docs/ORDER_SAFETY.md',
      'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/disclaimer.md',
    ];
    for (const url of required) {
      expect(allContent).toContain(url);
    }
    // reject placeholder language
    expect(allContent).not.toMatch(/or equivalent public path/i);
    // reject bare ORDER_SAFETY.md without full path context (full URLs contain /docs/ORDER_SAFETY.md)
    expect(allContent).not.toMatch(/(?<!\/)ORDER_SAFETY\.md(?!\.md)/);
  });

  it('guards against absolute private/local paths in pilot content', () => {
    const privatePrefixes = ['/home/', '/Users/', 'C:/', 'C:\\\\', '.local/', 'localhost', '127.0.0.1'];
    for (const fname of PILOT_MDX_FILES) {
      const content = readFileSync(join(DOCS_DIR, fname), 'utf8');
      for (const prefix of privatePrefixes) {
        // allow only if in allowed prose contexts, but for pilot reject hard-coded absolute
        expect(content).not.toContain(prefix);
      }
    }
  });

  it('Practice/Live prose explicitly states provenance independence (no conflation with Sample or Live data)', () => {
    const modesContent = readFileSync(join(DOCS_DIR, 'product-modes.mdx'), 'utf8');
    // must explicitly separate operating mode from provenance
    expect(modesContent).toMatch(/provenance.*independent|independent.*provenance/i);
    // must not claim Practice implies Sample or Live implies Live data (target old conflating phrases only)
    expect(modesContent).not.toMatch(/Simulated trading with sample data|Real trading with live market data/i);
    expect(modesContent).toContain('Explore');
    expect(modesContent).toContain('Practice');
    expect(modesContent).toContain('Live');
    // provenance labels separate
    expect(modesContent).toContain('Sample');
    expect(modesContent).toContain('Unavailable');
    expect(modesContent).toContain('Stale');
  });
});
