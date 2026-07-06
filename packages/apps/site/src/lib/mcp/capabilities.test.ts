import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

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
    expect(docsIndex.docs.some((doc) => doc.sourcePath === 'docs/DESKTOP.md')).toBe(true);
    expect(docsIndex.docs.some((doc) => doc.sourcePath.startsWith('docs/setup/'))).toBe(true);
    expect(docsIndex.docs.some((doc) => doc.sourcePath.startsWith('docs/releases/'))).toBe(true);
    expect(docsIndex.packages.some((pkg) => pkg.sourcePath === 'packages/apps/terminal/README.md')).toBe(true);
  });

  it('includes the central app version in generated docs metadata', () => {
    expect(docsIndex.version).toBe(APP_VERSION);
    expect(docsIndex.versionTag).toBe(APP_VERSION_TAG);
  });

  it('publishes the chart ownership boundary through generated architecture docs', () => {
    const architectureDoc = docsIndex.docs.find((doc) => doc.sourcePath === 'docs/ARCHITECTURE.md');

    expect(architectureDoc?.content).toContain('Chart ownership boundary');
    expect(architectureDoc?.content).toContain('src/lib/lightweightChartRuntime.ts');
    expect(architectureDoc?.content).toContain('Plotly');
    expect(architectureDoc?.content).toContain('createFlintPlotlyTheme');
    expect(architectureDoc?.content).toContain('createFlintChartDrawingRenderPlan');
    expect(architectureDoc?.content).toContain('createFlintChartDrawingRenderPlanDiff');
    expect(architectureDoc?.content).toContain('createFlintChartIndicatorSeriesRenderPlan');
    expect(architectureDoc?.content).toContain('createFlintChartIndicatorSeriesRenderPlanDiff');
    expect(architectureDoc?.content).toContain('createFlintChartOIProfileBarData');
    expect(architectureDoc?.content).toContain('runtime adapter');
  });

  it('publishes the current terminal widget catalogue count', () => {
    const architectureDoc = docsIndex.docs.find((doc) => doc.sourcePath === 'docs/ARCHITECTURE.md');
    const userGuideDoc = docsIndex.docs.find((doc) => doc.sourcePath === 'docs/USER_GUIDE.md');

    expect(architectureDoc?.content).toContain('101 widgets');
    expect(architectureDoc?.content).toContain('26 trading + 49 analysis + 26 utility');
    expect(userGuideDoc?.content).toContain('The widgets (101)');
    expect(`${architectureDoc?.content ?? ''}\n${userGuideDoc?.content ?? ''}`).not.toContain(`82 ${'widgets'}`);
    expect(`${architectureDoc?.content ?? ''}\n${userGuideDoc?.content ?? ''}`).not.toContain(`38 ${'analysis'}`);
  });

  it('publishes the current INDstocks reset semantics through generated broker docs', () => {
    const userGuideDoc = docsIndex.docs.find((doc) => doc.sourcePath === 'docs/USER_GUIDE.md');
    const compatibilityDoc = docsIndex.docs.find((doc) => doc.sourcePath === 'docs/COMPATIBILITY.md');
    const brokerDocs = `${userGuideDoc?.content ?? ''}\n${compatibilityDoc?.content ?? ''}`;
    const staleIndstocksPhrase = 'INDmoney uses a dashboard-generated ' + '24-hour token';

    expect(userGuideDoc?.content).toContain('daily 06:00 IST dashboard cycle');
    expect(compatibilityDoc?.content).toContain('daily 06:00 IST dashboard cycle');
    expect(brokerDocs).not.toContain(staleIndstocksPhrase);
  });

  it('keeps homepage facts aligned with the audited gateway and widget state', () => {
    const pageSource = readFileSync(resolve(process.cwd(), 'src/app/page.tsx'), 'utf8');

    expect(pageSource).toContain('<strong>101</strong>');
    expect(pageSource).toContain('Native broker contract and routing are safety-gated');
    expect(pageSource).toContain('adapters stay behind credential, ACL, and SDK checks');
    expect(pageSource).not.toContain('<strong>82</strong>');
    expect(pageSource).not.toContain('Native and OpenAlgo broker integrations documented');
  });

  it('keeps the desktop app install path visible on the website', () => {
    const pageSource = readFileSync(resolve(process.cwd(), 'src/app/page.tsx'), 'utf8');
    const headerSource = readFileSync(resolve(process.cwd(), 'src/components/site-header.tsx'), 'utf8');
    const footerSource = readFileSync(resolve(process.cwd(), 'src/components/site-footer.tsx'), 'utf8');
    const desktopDoc = docsIndex.docs.find((doc) => doc.sourcePath === 'docs/DESKTOP.md');

    expect(pageSource).toContain('href="/docs/desktop"');
    expect(pageSource).toContain('Install desktop app');
    expect(headerSource).toContain("href: '/docs/desktop'");
    expect(footerSource).toContain('href="/docs/desktop"');
    expect(desktopDoc?.content).toContain('GitHub Releases');
    expect(desktopDoc?.content).toContain('Launch FlintTrade and complete the in-app Setup flow');
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
