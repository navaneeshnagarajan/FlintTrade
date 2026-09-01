import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import {
  repositoryBrowseUrl,
  rewriteMarkdownRepositoryLinks,
  rewriteRepositoryLink,
  statRepositoryPath,
} from './rewrite-repository-links.mjs';

const SITE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const REPO_ROOT = resolve(SITE_ROOT, '..', '..', '..');

const GITHUB = {
  owner: 'navaneeshnagarajan',
  name: 'FlintTrade',
  ref: 'main',
};

function rewriteOptions(overrides = {}) {
  return {
    repoRoot: REPO_ROOT,
    ...GITHUB,
    docRouteBySourcePath: new Map([
      ['docs/DESKTOP.md', '/docs/desktop'],
      ['disclaimer.md', '/docs/disclaimer'],
      ['docs/setup/linux.md', '/docs/setup/linux'],
    ]),
    repositoryFileUrls: new Map(),
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
      rewriteRepositoryLink('../scripts/install/', 'docs/DESKTOP.md', rewriteOptions({ ref: sha })),
    ).toBe(`https://github.com/navaneeshnagarajan/FlintTrade/tree/${sha}/scripts/install`);
  });

  it('leaves absolute, hash, and unknown relative targets unchanged', () => {
    expect(rewriteRepositoryLink('https://example.test/a', 'docs/DESKTOP.md', rewriteOptions())).toBe(
      null,
    );
    expect(rewriteRepositoryLink('#release-ci', 'docs/DESKTOP.md', rewriteOptions())).toBe(null);
    expect(
      rewriteRepositoryLink('../does-not-exist/anywhere.py', 'docs/DESKTOP.md', rewriteOptions()),
    ).toBe(null);
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
    const recorded = new Map();
    rewriteRepositoryLink('../scripts/install/', 'docs/DESKTOP.md', {
      ...rewriteOptions(),
      onRepoPath(repoPath, url) {
        recorded.set(repoPath, url);
      },
    });
    expect(recorded.get('scripts/install')).toBe(
      'https://github.com/navaneeshnagarajan/FlintTrade/tree/main/scripts/install',
    );
  });
});

describe('DESKTOP.md and setup-guide rewrite', () => {
  it('rewrites every DESKTOP.md repo-relative source link to GitHub', () => {
    const desktopSource = readFileSync(join(REPO_ROOT, 'docs/DESKTOP.md'), 'utf8');
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
    const rewritten = rewriteMarkdownRepositoryLinks(linux, 'docs/setup/linux.md', rewriteOptions());
    expect(rewritten).toContain(
      'https://github.com/navaneeshnagarajan/FlintTrade/tree/main/scripts/install',
    );
    expect(rewritten).not.toContain('](../../scripts/install/)');
  });
});

describe('repositoryBrowseUrl and statRepositoryPath', () => {
  it('builds blob and tree URLs with the requested ref', () => {
    expect(
      repositoryBrowseUrl({
        ...GITHUB,
        repoPath: 'scripts/install/',
        isDirectory: true,
      }),
    ).toBe('https://github.com/navaneeshnagarajan/FlintTrade/tree/main/scripts/install');
  });

  it('distinguishes files from directories in a fixture tree', () => {
    const root = mkdtempSync(join(tmpdir(), 'flinttrade-stat-'));
    mkdirSync(join(root, 'scripts', 'install'), { recursive: true });
    writeFileSync(join(root, 'packaging.py'), 'print("ok")\n');

    expect(statRepositoryPath(root, 'scripts/install/')).toEqual({ isDirectory: true });
    expect(statRepositoryPath(root, 'packaging.py')).toEqual({ isDirectory: false });
    expect(statRepositoryPath(root, 'missing.py')).toBeNull();
  });
});
