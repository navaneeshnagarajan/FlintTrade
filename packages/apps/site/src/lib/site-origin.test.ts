import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import { CANONICAL_SITE_ORIGIN, hostedMcpUrl, siteOriginFrom } from './site-origin';

describe('site origin', () => {
  it('prefers the forwarded host and proto from the request', () => {
    expect(
      siteOriginFrom({
        host: 'localhost:3000',
        forwardedHost: 'flinttrade.vercel.app',
        forwardedProto: 'https',
      }),
    ).toBe('https://flinttrade.vercel.app');
  });

  it('uses http for localhost when proto is absent', () => {
    expect(siteOriginFrom({ host: 'localhost:3000' })).toBe('http://localhost:3000');
  });

  it('falls back to VERCEL_URL then the canonical public origin', () => {
    expect(siteOriginFrom(undefined, { VERCEL_URL: 'preview.vercel.app' })).toBe(
      'https://preview.vercel.app',
    );
    expect(siteOriginFrom()).toBe(CANONICAL_SITE_ORIGIN);
  });

  it('builds a copy-pasteable MCP URL', () => {
    expect(hostedMcpUrl('https://flinttrade.vercel.app')).toBe('https://flinttrade.vercel.app/api/mcp');
    expect(hostedMcpUrl('https://flinttrade.vercel.app/')).toBe('https://flinttrade.vercel.app/api/mcp');
  });
});

describe('hosted MCP snippet copy', () => {
  it('does not leave a placeholder host on the homepage or MCP page', () => {
    const home = readFileSync(resolve(process.cwd(), 'src/app/page.tsx'), 'utf8');
    const mcp = readFileSync(resolve(process.cwd(), 'src/app/mcp/page.tsx'), 'utf8');
    const combined = `${home}\n${mcp}`;

    expect(combined).not.toContain('<your-site>');
    expect(combined).not.toContain('<your-flinttrade-site>');
    expect(home).toContain('hostedMcpUrl');
    expect(mcp).toContain('hostedMcpUrl');
    expect(home).toContain('resolveSiteOrigin');
    expect(mcp).toContain('resolveSiteOrigin');
  });
});
