import { describe, expect, it } from 'vitest';

import {
  DOCS_MCP_TOOL_NAMES,
  assertDocsMcpSafety,
  recommendTests,
  searchDocs,
} from './capabilities';
import { docsIndex } from './data';

describe('docs index generation', () => {
  it('contains root docs, package READMEs, setup docs, and release docs', () => {
    expect(docsIndex.docs.some((doc) => doc.sourcePath === 'docs/README.md')).toBe(true);
    expect(docsIndex.docs.some((doc) => doc.sourcePath.startsWith('docs/setup/'))).toBe(true);
    expect(docsIndex.docs.some((doc) => doc.sourcePath.startsWith('docs/releases/'))).toBe(true);
    expect(docsIndex.packages.some((pkg) => pkg.sourcePath === 'packages/terminal/README.md')).toBe(true);
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
    const recommendation = recommendTests(['packages/terminal/src/foo.tsx']);

    expect(recommendation.commands).toContain('cd packages/terminal && npm run typecheck');
    expect(recommendation.commands).toContain('cd packages/terminal && npm run test');
  });

  it('does not expose trading or broker tools from the docs MCP', () => {
    assertDocsMcpSafety();
    const names = DOCS_MCP_TOOL_NAMES.join(' ');

    expect(names).not.toMatch(/place_order|trade|broker|fund|credential/i);
  });
});
