import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import { githubUrlForDocsSlug } from './repo-source-links';

const REPO_ROOT = resolve(process.cwd(), '..', '..', '..');
const SITE_ROOT = process.cwd();

describe('docs markdown is left unchanged', () => {
  it('keeps DESKTOP.md repo-relative source links in the git tree', () => {
    const desktopSource = readFileSync(join(REPO_ROOT, 'docs/DESKTOP.md'), 'utf8');
    expect(desktopSource).toContain('](../scripts/install/)');
    expect(desktopSource).toContain('](../packaging/desktop_backend.py)');
    expect(desktopSource).toContain('](../.github/workflows/desktop-release.yml)');
    expect(desktopSource).toContain('](../packages/apps/desktop/electron/)');
    expect(desktopSource).toContain('](../packages/apps/desktop/splash/)');
    expect(desktopSource).toContain('](../packages/apps/desktop/resources/bootstrap/)');
  });
});

describe('generated docs content', () => {
  it('rewrites DESKTOP.md source links to GitHub instead of /docs/... routes', () => {
    const generated = readFileSync(join(SITE_ROOT, 'content/docs/desktop.mdx'), 'utf8');
    expect(generated).toContain(
      'https://github.com/navaneeshnagarajan/FlintTrade/tree/main/scripts/install',
    );
    expect(generated).toContain(
      'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/packaging/desktop_backend.py',
    );
    expect(generated).toContain(
      'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/.github/workflows/desktop-release.yml',
    );
    expect(generated).toContain(
      'https://github.com/navaneeshnagarajan/FlintTrade/tree/main/packages/apps/desktop/electron',
    );
    expect(generated).toContain(
      'https://github.com/navaneeshnagarajan/FlintTrade/tree/main/packages/apps/desktop/splash',
    );
    expect(generated).toContain(
      'https://github.com/navaneeshnagarajan/FlintTrade/tree/main/packages/apps/desktop/resources/bootstrap',
    );
    expect(generated).not.toContain('](../scripts/install/)');
    expect(generated).not.toContain('](/docs/scripts/install');
    expect(generated).not.toContain('](/docs/packaging/desktop_backend.py)');
    expect(generated).not.toContain('](/docs/.github/workflows/desktop-release.yml)');
  });

  it('records leftover /docs/<repo-path> redirects for the generated source map', () => {
    const recorded = JSON.parse(
      readFileSync(join(SITE_ROOT, 'src/generated/repo-source-links.json'), 'utf8'),
    ) as Record<string, string>;
    expect(recorded['scripts/install']).toBe(
      'https://github.com/navaneeshnagarajan/FlintTrade/tree/main/scripts/install',
    );
    expect(recorded['packaging/desktop_backend.py']).toBe(
      'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/packaging/desktop_backend.py',
    );
    expect(recorded['.github/workflows/desktop-release.yml']).toBe(
      'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/.github/workflows/desktop-release.yml',
    );
  });
});

describe('githubUrlForDocsSlug', () => {
  const links = {
    'scripts/install': 'https://github.com/navaneeshnagarajan/FlintTrade/tree/main/scripts/install',
    'packaging/desktop_backend.py':
      'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/packaging/desktop_backend.py',
    '.github/workflows/desktop-release.yml':
      'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/.github/workflows/desktop-release.yml',
  };

  it('redirects the leftover /docs/<repo-path> slugs to GitHub', () => {
    expect(githubUrlForDocsSlug(['scripts', 'install'], links)).toBe(links['scripts/install']);
    expect(githubUrlForDocsSlug(['packaging', 'desktop_backend.py'], links)).toBe(
      links['packaging/desktop_backend.py'],
    );
    expect(githubUrlForDocsSlug(['.github', 'workflows', 'desktop-release.yml'], links)).toBe(
      links['.github/workflows/desktop-release.yml'],
    );
  });

  it('returns null for unknown docs slugs', () => {
    expect(githubUrlForDocsSlug(['no-such-page'], links)).toBeNull();
    expect(githubUrlForDocsSlug(undefined, links)).toBeNull();
    expect(githubUrlForDocsSlug([], links)).toBeNull();
  });
});

describe('site generator wiring', () => {
  it('hooks the filesystem-backed rewriter from generate-content', () => {
    const generator = readFileSync(join(SITE_ROOT, 'scripts/generate-content.mjs'), 'utf8');
    expect(generator).toContain('rewrite-repository-links.mjs');
    expect(generator).toContain('rewriteMarkdownRepositoryLinks');
    expect(generator).toContain('repo-source-links.json');
    expect(generator).toContain('FLINTTRADE_SITE_SOURCE_SHA');
  });

  it('redirects leftover /docs/<repo-path> requests from the docs page', () => {
    const page = readFileSync(join(SITE_ROOT, 'src/app/docs/[[...slug]]/page.tsx'), 'utf8');
    expect(page).toContain('githubUrlForDocsSlug');
    expect(page).toContain('repo-source-links.json');
    expect(page).toContain('redirect(githubUrl)');
  });

  it('includes the rewriter unit tests in the site Vitest config', () => {
    const config = readFileSync(join(SITE_ROOT, 'vitest.config.ts'), 'utf8');
    expect(config).toContain('scripts/**/*.test.mjs');
  });
});
