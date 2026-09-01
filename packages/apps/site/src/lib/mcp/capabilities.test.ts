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
    expect(architectureDoc?.content).toContain('createFlintChartIndicatorSeriesRenderPlanDiff');
    expect(architectureDoc?.content).toContain('createFlintChartOIProfileBarData');
    expect(architectureDoc?.content).toContain('runtime adapter');
  });

  it('publishes the current terminal widget catalogue count', () => {
    const architectureDoc = docsIndex.docs.find((doc) => doc.sourcePath === 'docs/ARCHITECTURE.md');
    const userGuideDoc = docsIndex.docs.find((doc) => doc.sourcePath === 'docs/USER_GUIDE.md');

    expect(architectureDoc?.content).toContain('71 widgets');
    expect(architectureDoc?.content).toContain('18 trading + 31 analysis + 22 utility');
    expect(userGuideDoc?.content).toContain('The widgets (71)');
    expect(`${architectureDoc?.content ?? ''}\n${userGuideDoc?.content ?? ''}`).not.toContain(`69 ${'widgets'}`);
    expect(`${architectureDoc?.content ?? ''}\n${userGuideDoc?.content ?? ''}`).not.toContain(`29 ${'analysis'}`);
  });

  it('keeps broker catalogue count pins aligned at 37', () => {
    const claude = readFileSync(resolve(process.cwd(), '../../../CLAUDE.md'), 'utf8');
    const agents = readFileSync(resolve(process.cwd(), '../../../AGENTS.md'), 'utf8');

    expect(claude).toContain('`BROKER_CATALOG` (37 brokers)');
    expect(agents).toContain('37 brokers');
    expect(claude).not.toContain('`BROKER_CATALOG` (35 brokers)');
    expect(agents).not.toContain('35 brokers');
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

    expect(pageSource).toContain('<strong>71</strong>');
    expect(pageSource).not.toContain('<strong>84</strong>');
    expect(pageSource).toContain('Native broker contract and routing are safety-gated');
    expect(pageSource).toContain('adapters stay behind credential, ACL, and SDK checks');
    expect(pageSource).not.toContain('<strong>84</strong>');
    expect(pageSource).not.toContain('Native and OpenAlgo broker integrations documented');
  });

  it('keeps the web-app install path and desktop guide reachable from the website', () => {
    const pageSource = readFileSync(resolve(process.cwd(), 'src/app/page.tsx'), 'utf8');
    const headerSource = readFileSync(resolve(process.cwd(), 'src/components/site-header.tsx'), 'utf8');
    const footerSource = readFileSync(resolve(process.cwd(), 'src/components/site-footer.tsx'), 'utf8');
    const downloadSource = readFileSync(resolve(process.cwd(), 'src/app/download/page.tsx'), 'utf8');
    const desktopDoc = docsIndex.docs.find((doc) => doc.sourcePath === 'docs/DESKTOP.md');

    // The download surface distinguishes the source-built web app from the
    // Electron shell and carries Electron commands only for a complete release.
    expect(headerSource).toContain("href: '/download'");
    expect(pageSource).toContain('href="/download"');
    expect(pageSource).toContain('Install the web app');
    expect(pageSource).toContain('web-install.sh');
    expect(pageSource).toContain('web-install.ps1');
    expect(pageSource).not.toContain('Download desktop app');
    expect(downloadSource).toContain('install.sh | bash');
    expect(downloadSource).toContain('install.ps1 | iex');
    // The desktop guide stays reachable from the homepage, footer, and docs.
    expect(pageSource).toContain('href="/docs/desktop"');
    expect(footerSource).toContain('href="/docs/desktop"');
    expect(desktopDoc?.content).toContain('exactly four shell installers plus one checksum');
    expect(desktopDoc?.content).toContain('source-built web-app install from Electron-shell installers');
    expect(desktopDoc?.content).toContain('withholds Electron commands and download buttons unless one release');
    expect(desktopDoc?.content).toContain('inspectable source checkout on first launch');
    expect(desktopDoc?.content).not.toContain('desktop release manifest');
  });

  it('hero leads with the web-app install path, one explore-demo secondary, and no desktop-download CTA', () => {
    const pageSource = readFileSync(resolve(process.cwd(), 'src/app/page.tsx'), 'utf8');
    // Extract only the hero-actions block for href/target/MCP assertions
    const heroMatch = pageSource.match(/<div className="hero-actions">[\s\S]*?<\/div>/);
    const heroActions = heroMatch ? heroMatch[0] : pageSource;
    // exactly one primary on the FULL page (global hierarchy guard)
    const primaryMatches = pageSource.match(/className="button primary"/g) || [];
    expect(primaryMatches.length).toBe(1);
    expect(heroActions).toContain('href="/download"');
    expect(heroActions).toContain('Install the web app');
    expect(heroActions).toContain('href="/demo-app/welcome"');
    expect(heroActions).toContain('target="_blank"');
    expect(heroActions).toContain('Explore demo');
    expect((heroActions.match(/href="\/download"/g) || []).length).toBe(1);
    expect(heroActions).not.toContain('Download desktop app');
    expect(heroActions).not.toContain('Run the web app');
    expect(heroActions).not.toContain('Check installer status');
    // no retired operating-mode strings in rendered copy (whole page OK)
    expect(pageSource).not.toMatch(/sandbox testing|Sandbox Demo|Demo Mode|paper trading|paper order|demo data/i);
    // MCP absent from hero-actions only
    expect(heroActions).not.toContain('Use the docs MCP');
    expect(heroActions).not.toContain('/mcp');
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
