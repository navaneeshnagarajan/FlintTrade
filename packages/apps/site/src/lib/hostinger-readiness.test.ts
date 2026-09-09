import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

function readSite(relativePath: string): string {
  return readFileSync(resolve(process.cwd(), relativePath), 'utf8');
}

describe('Hostinger / generic Node hosting readiness', () => {
  it('gates Vercel Speed Insights so a generic Node host can boot without Vercel', () => {
    const insights = readSite('src/components/optional-speed-insights.tsx');
    const layout = readSite('src/app/layout.tsx');

    expect(layout).toContain('OptionalSpeedInsights');
    expect(insights).toContain('@vercel/speed-insights/next');
    expect(insights).toMatch(/process\.env\.VERCEL/);
  });

  it('documents a VPS Node run path and the public site URL env var', () => {
    const readme = readSite('README.md');

    expect(readme).toMatch(/Hostinger|VPS/);
    expect(readme).toContain('FLINTTRADE_SITE_URL');
    expect(readme).toContain('FLINTTRADE_SITE_ORIGINS');
    expect(readme).toContain('next start');
    expect(readme).toContain('/api/mcp');
    expect(readme).toMatch(/Node\.js >=? ?22|Node >=? ?22|node.+22/i);
    expect(readme).toMatch(/not static-only|not static only|Node server/i);
  });

  it('keeps metadataBase on the configurable site origin helper', () => {
    const layout = readSite('src/app/layout.tsx');
    expect(layout).toContain('siteMetadataOrigin');
    expect(layout).toContain('metadataBase');
  });
});
