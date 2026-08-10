/**
 * Public-surface guard — the published docs and repo-root markdown must not
 * point readers at the maintainer's private working notes (the gitignored
 * `.local/` tree, the reference-research captures) or name personal
 * machines.
 *
 * Scanned surfaces:
 *   1. Every generated docs-index entry (docs[].content and
 *      packages[].content) — what the site and docs MCP actually publish.
 *   2. The repo files readme.md, AGENTS.md, changelog.md, disclaimer.md,
 *      PLAN.md (the curated public roadmap since 2026-07-28; the detailed
 *      working plan moved to the maintainer's private workspace) and every
 *      docs/*.md and docs/*.mdx on disk.
 *
 * docs/superpowers/plans/ was removed from the repo on 2026-07-28 (archived
 * privately per the plan's own Step B); the directory is skipped in case a
 * stale checkout still carries it.
 */

import { readdirSync, readFileSync } from 'node:fs';
import { join, relative, resolve, sep } from 'node:path';

import { describe, expect, it } from 'vitest';

import { docsIndex } from './mcp/data';

const REPO_ROOT = resolve(process.cwd(), '..', '..', '..');

/** Substrings that must never appear on any public surface. */
const DENIED_SUBSTRINGS = [
  '.local/',
  'reference-research',
  'Nitro',
  // source contract additions for Hostinger staging prep privacy + hosting truth + reproducibility
  'C:/Users/USER',
  'WINDOWS_HOST',
  '/c/Users/navan',
  'PYTHONPATH=C:',
  'manually upload `.next/static/` + root HTML/JS',
  'Recommended for Hostinger static hosting trial',
] as const;

/**
 * Documented public conventions that legitimately mention gitignored
 * `.local/` locations (external test-dep clones, the SDK audit cache, the
 * opt-in agent-context scaffold) or standard Linux `~/.local` user paths.
 * These are repo-documented mechanisms, not private working notes; they are
 * stripped before the `.local/` check runs. Order matters — longer, more
 * specific entries first.
 */
const ALLOWED_LOCAL_MENTIONS = [
  '`.local/` (gitignored)',
  '~/.local/',
  '.local/external',
  '.local/sdk-audit',
  '.local/agent-context',
  // docs/CI.md quotes test.yml's paths-ignore glob verbatim.
  '.local/**',
] as const;

/**
 * Files whose remaining `.local/` mentions are accepted:
 * - AGENTS.md documents the spec-first working convention (design specs live
 *   in the maintainer's gitignored `.local/specs/` tree) — a convention
 *   statement, not a citation of a specific private file.
 * - The 2026-05-20 modernisation design spec is the historical record of the
 *   archive operation itself, so it necessarily describes `.local/archive/`.
 * The 'Nitro' and 'reference-research' checks still apply to these files.
 */
const LOCAL_EXEMPT_FILES = [
  'AGENTS.md',
  'docs/superpowers/specs/2026-05-20-public-repo-modernisation-design.md',
] as const;

/** Directories under docs/ that are not scanned (removed from the repo). */
const SKIPPED_DOC_DIRS = ['docs/superpowers/plans'] as const;

function violationsIn(sourcePath: string, content: string): string[] {
  const violations: string[] = [];
  for (const denied of DENIED_SUBSTRINGS) {
    let haystack = content;
    if (denied === '.local/') {
      if (LOCAL_EXEMPT_FILES.some((file) => sourcePath.endsWith(file))) continue;
      for (const allowed of ALLOWED_LOCAL_MENTIONS) {
        haystack = haystack.split(allowed).join('');
      }
    }
    if (haystack.includes(denied)) {
      violations.push(`${sourcePath}: contains "${denied}"`);
    }
  }
  return violations;
}

function listMarkdownFiles(dir: string): string[] {
  const results: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const fullPath = join(dir, entry.name);
    const repoRelative = relative(REPO_ROOT, fullPath).split(sep).join('/');
    if (entry.isDirectory()) {
      if (SKIPPED_DOC_DIRS.some((skipped) => repoRelative === skipped)) continue;
      results.push(...listMarkdownFiles(fullPath));
    } else if (entry.name.endsWith('.md') || entry.name.endsWith('.mdx')) {
      results.push(fullPath);
    }
  }
  return results;
}

describe('no private references on public surfaces', () => {
  it('keeps the generated docs index free of private references', () => {
    const violations: string[] = [];
    for (const doc of docsIndex.docs) {
      violations.push(...violationsIn(doc.sourcePath, doc.content));
    }
    for (const pkg of docsIndex.packages) {
      violations.push(...violationsIn(pkg.sourcePath, pkg.content));
    }
    expect(violations).toEqual([]);
  });

  it('keeps repo-root markdown and docs/ free of private references', () => {
    const rootFiles = ['readme.md', 'AGENTS.md', 'changelog.md', 'disclaimer.md', 'PLAN.md'];
    const files = [
      ...rootFiles.map((file) => resolve(REPO_ROOT, file)),
      ...listMarkdownFiles(resolve(REPO_ROOT, 'docs')),
    ];

    const violations: string[] = [];
    for (const file of files) {
      const repoRelative = relative(REPO_ROOT, file).split(sep).join('/');
      violations.push(...violationsIn(repoRelative, readFileSync(file, 'utf8')));
    }
    expect(violations).toEqual([]);
  });
});
