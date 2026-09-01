import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  repositoryBrowseUrl,
  rewriteMarkdownRepositoryLinks,
  rewriteRepositoryLink,
  statRepositoryPath,
} from '../../scripts/rewrite-repository-links.mjs';

import { githubUrlForDocsSlug } from './repo-source-links';

const REPO_ROOT = resolve(process.cwd(), '..', '..', '..');
const SITE_ROOT = process.cwd();

const GITHUB = {
  owner: 'navaneeshnagarajan',
  name: 'FlintTrade',
  ref: 'main',
};

function rewriteOptions(overrides: Record<string, unknown> = {}) {
  return {
    repoRoot: REPO_ROOT,
    ...GITHUB,
    docRouteBySourcePath: new Map<string, string>([
      ['docs/DESKTOP.md', '/docs/desktop'],
      ['disclaimer.md', '/docs/disclaimer'],
      ['docs/setup/linux.md', '/docs/setup/linux'],
    ]),
    repositoryFileUrls: new Map<string, string>(),
    ...overrides,
  };
}

describe('rewriteRepositoryLink', () => {
  it('rewrites a repo file to a GitHub blob URL on the given ref', () => {
    expect(
      rewriteRepositoryLink('../packaging/desktop_backend.py', 'docs/DESKTOP.md', rewriteOptions()),
    ).toBe(
      'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/packaging/desktop_backend.py',
    );
  });

  it('rewrites a repo directory to a GitHub tree URL', () => {
    expect(rewriteRepositoryLink('../scripts/install/', 'docs/DESKTOP.md', rewriteOptions())).toBe(
      'https://github.com/navaneeshnagarajan/FlintTrade/tree/main/scripts/install',
    );
  });

  it('rewrites .github workflow files that Fumadocs would publish as /docs/.github/...', () => {
    expect(
      rewriteRepositoryLink(
        '../.github/workflows/desktop-release.yml',
        'docs/DESKTOP.md',
        rewriteOptions(),
      ),
    ).toBe(
      'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/.github/workflows/desktop-release.yml',
    );
  });

  it('keeps generated docs pages on-site instead of sending them to GitHub', () => {
    expect(rewriteRepositoryLink('../disclaimer.md', 'docs/USER_GUIDE.md', rewriteOptions())).toBe(
      '/docs/disclaimer',
    );
    expect(rewriteRepositoryLink('../DESKTOP.md', 'docs/setup/QUICKSTART.md', rewriteOptions())).toBe(
      '/docs/desktop',
    );
  });

  it('preserves fragment identifiers', () => {
    expect(
      rewriteRepositoryLink('../packaging/desktop_backend.py#L10', 'docs/DESKTOP.md', rewriteOptions()),
    ).toBe(
      'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/packaging/desktop_backend.py#L10',
    );
  });

  it('uses the deployment ref rather than a hardcoded main branch', () => {
    const sha = '0123456789abcdef0123456789abcdef01234567';
    expect(
      rewriteRepositoryLink(
        '../scripts/install/',
        'docs/DESKTOP.md',
        rewriteOptions({ ref: sha }),
      ),
    ).toBe(`https://github.com/navaneeshnagarajan/FlintTrade/tree/${sha}/scripts/install`);
  });

  it('leaves absolute, hash, and unknown relative targets unchanged', () => {
    expect(rewriteRepositoryLink('https://example.test/a', 'docs/DESKTOP.md', rewriteOptions())).toBe(
      null,
    );
    expect(rewriteRepositoryLink('#release-ci', 'docs/DESKTOP.md', rewriteOptions())).toBe(null);
    expect(rewriteRepositoryLink('../does-not-exist/anywhere.py', 'docs/DESKTOP.md', rewriteOptions())).toBe(
      null,
    );
  });

  it('refuses path traversal outside the repository root', () => {
    expect(statRepositoryPath(REPO_ROOT, '../outside')).toBeNull();
    expect(rewriteRepositoryLink('../../../etc/passwd', 'docs/DESKTOP.md', rewriteOptions())).toBe(
      null,
    );
  });

  it('falls back to the allowlist when the path is absent from the working tree', () => {
    const isolatedRoot = mkdtempSync(join(tmpdir(), 'flinttrade-site-links-'));
    expect(
      rewriteRepositoryLink('../changelog.md', 'docs/README.md', {
        ...rewriteOptions({ repoRoot: isolatedRoot }),
        repositoryFileUrls: new Map([
          ['changelog.md', 'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/changelog.md'],
        ]),
      }),
    ).toBe('https://github.com/navaneeshnagarajan/FlintTrade/blob/main/changelog.md');
  });

  it('records rewritten repo paths for leftover /docs/<path> redirects', () => {
    const recorded = new Map<string, string>();
    rewriteRepositoryLink('../scripts/install/', 'docs/DESKTOP.md', {
      ...rewriteOptions(),
      onRepoPath(repoPath: string, url: string) {
        recorded.set(repoPath, url);
      },
    });
    expect(recorded.get('scripts/install')).toBe(
      'https://github.com/navaneeshnagarajan/FlintTrade/tree/main/scripts/install',
    );
  });
});

describe('DESKTOP.md source links', () => {
  const desktopSource = readFileSync(join(REPO_ROOT, 'docs/DESKTOP.md'), 'utf8');

  it('leaves the docs markdown relative source links unchanged', () => {
    expect(desktopSource).toContain('](../scripts/install/)');
    expect(desktopSource).toContain('](../packaging/desktop_backend.py)');
    expect(desktopSource).toContain('](../.github/workflows/desktop-release.yml)');
    expect(desktopSource).toContain('](../packages/apps/desktop/electron/)');
    expect(desktopSource).toContain('](../packages/apps/desktop/splash/)');
    expect(desktopSource).toContain('](../packages/apps/desktop/resources/bootstrap/)');
  });

  it('rewrites every DESKTOP.md repo-relative source link to GitHub', () => {
    const rewritten = rewriteMarkdownRepositoryLinks(
      desktopSource,
      'docs/DESKTOP.md',
      rewriteOptions(),
    );

    expect(rewritten).toContain(
      'https://github.com/navaneeshnagarajan/FlintTrade/tree/main/scripts/install',
    );
    expect(rewritten).toContain(
      'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/packaging/desktop_backend.py',
    );
    expect(rewritten).toContain(
      'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/.github/workflows/desktop-release.yml',
    );
    expect(rewritten).toContain(
      'https://github.com/navaneeshnagarajan/FlintTrade/tree/main/packages/apps/desktop/electron',
    );
    expect(rewritten).toContain(
      'https://github.com/navaneeshnagarajan/FlintTrade/tree/main/packages/apps/desktop/splash',
    );
    expect(rewritten).toContain(
      'https://github.com/navaneeshnagarajan/FlintTrade/tree/main/packages/apps/desktop/resources/bootstrap',
    );
    expect(rewritten).not.toContain('](../scripts/install/)');
    expect(rewritten).not.toContain('](../packaging/desktop_backend.py)');
    expect(rewritten).not.toContain('](/docs/scripts/install');
    expect(rewritten).not.toContain('](/docs/packaging/desktop_backend.py)');
  });

  it('rewrites nested setup-guide source links the same way', () => {
    const linux = readFileSync(join(REPO_ROOT, 'docs/setup/linux.md'), 'utf8');
    const rewritten = rewriteMarkdownRepositoryLinks(
      linux,
      'docs/setup/linux.md',
      rewriteOptions(),
    );
    expect(rewritten).toContain(
      'https://github.com/navaneeshnagarajan/FlintTrade/tree/main/scripts/install',
    );
    expect(rewritten).not.toContain('](../../scripts/install/)');
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

  it('builds blob and tree URLs with the requested ref', () => {
    expect(
      repositoryBrowseUrl({
        ...GITHUB,
        repoPath: 'scripts/install/',
        isDirectory: true,
      }),
    ).toBe('https://github.com/navaneeshnagarajan/FlintTrade/tree/main/scripts/install');
  });
});

describe('statRepositoryPath', () => {
  it('distinguishes files from directories in a fixture tree', () => {
    const root = mkdtempSync(join(tmpdir(), 'flinttrade-stat-'));
    mkdirSync(join(root, 'scripts', 'install'), { recursive: true });
    writeFileSync(join(root, 'packaging.py'), 'print("ok")\n');

    expect(statRepositoryPath(root, 'scripts/install/')).toEqual({ isDirectory: true });
    expect(statRepositoryPath(root, 'packaging.py')).toEqual({ isDirectory: false });
    expect(statRepositoryPath(root, 'missing.py')).toBeNull();
  });
});
