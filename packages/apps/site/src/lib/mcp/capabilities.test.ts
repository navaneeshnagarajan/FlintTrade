import { describe, expect, it } from 'vitest';

import {
  DOCS_MCP_TOOL_NAMES,
  assertDocsMcpSafety,
  explainRepoPath,
  recommendTests,
  searchDocs,
} from './capabilities';
import { docsIndex } from './data';
import { APP_VERSION, APP_VERSION_TAG } from '../version';

describe('docs index generation', () => {
  it('contains root docs, package READMEs, setup docs, and release docs', () => {
    expect(docsIndex.docs.some((doc) => doc.sourcePath === 'docs/README.md')).toBe(true);
    expect(docsIndex.docs.some((doc) => doc.sourcePath === 'disclaimer.md')).toBe(true);
    expect(docsIndex.docs.some((doc) => doc.sourcePath.startsWith('docs/setup/'))).toBe(true);
    expect(docsIndex.docs.some((doc) => doc.sourcePath.startsWith('docs/releases/'))).toBe(true);
    expect(docsIndex.packages.some((pkg) => pkg.sourcePath === 'packages/apps/terminal/README.md')).toBe(true);
  });

  it('includes the central app version in generated docs metadata', () => {
    expect(docsIndex.version).toBe(APP_VERSION);
    expect(docsIndex.versionTag).toBe(APP_VERSION_TAG);
  });
});

describe('MCP capabilities', () => {
  it('searches contributor and terminal documentation', () => {
    const results = searchDocs('add terminal widget');
    const haystack = results.map((result) => `${result.title} ${result.sourcePath}`).join(' ');

    expect(haystack).toContain('terminal');
    expect(results.length).toBeGreaterThan(0);
  });

  it('recommends terminal checks for terminal source changes', () => {
    const recommendation = recommendTests(['packages/apps/terminal/src/foo.tsx']);

    expect(recommendation.commands).toContain('cd packages/apps/terminal && npm run typecheck');
    expect(recommendation.commands).toContain('cd packages/apps/terminal && npm run test');
  });

  it('recommends nested package checks for Python source changes', () => {
    const recommendation = recommendTests(['packages/services/journal/src/entries.py']);

    expect(recommendation.commands).toContain('python -m pytest packages/services/journal/tests/ -v --import-mode=importlib');
    expect(recommendation.reason).toContain('services/journal');
  });

  it('explains nested package paths from the generated package index', () => {
    expect(explainRepoPath('packages/apps/terminal/src/routes/HomeRoute.tsx')).toContain('Terminal');
  });

  it('does not expose trading or broker tools from the docs MCP', () => {
    assertDocsMcpSafety();
    const names = DOCS_MCP_TOOL_NAMES.join(' ');

    expect(names).not.toMatch(/place_order|trade|broker|fund|credential/i);
  });
});
