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

  it('does not trust an arbitrary Host header for copyable origins', () => {
    expect(siteOriginFrom({ host: 'evil.example' })).toBe(CANONICAL_SITE_ORIGIN);
    expect(siteOriginFrom({ host: 'localhost.attacker.example' })).toBe(CANONICAL_SITE_ORIGIN);
    expect(siteOriginFrom({ host: '127.evil.example' })).toBe(CANONICAL_SITE_ORIGIN);
  });

  it('does not trust an arbitrary forwarded host when Host is also untrusted', () => {
    expect(
      siteOriginFrom({
        host: 'evil.example',
        forwardedHost: 'phish.example',
        forwardedProto: 'https',
      }),
    ).toBe(CANONICAL_SITE_ORIGIN);
  });

  it('uses the first forwarded hop when that hop is an allowed host', () => {
    expect(
      siteOriginFrom({
        host: 'localhost:3000',
        forwardedHost: 'flinttrade.vercel.app, evil.example',
        forwardedProto: 'https, http',
      }),
    ).toBe('https://flinttrade.vercel.app');
  });

  it('ignores a poisoned first forwarded hop and falls back to a valid Host', () => {
    expect(
      siteOriginFrom({
        host: 'localhost:3000',
        forwardedHost: 'evil.example, flinttrade.vercel.app',
      }),
    ).toBe('http://localhost:3000');
  });

  it('allows only the canonical host, the exact VERCEL_URL, and loopback hosts', () => {
    expect(siteOriginFrom({ host: 'flinttrade.vercel.app' })).toBe('https://flinttrade.vercel.app');
    expect(
      siteOriginFrom({ host: 'custom.example' }, { VERCEL_URL: 'https://custom.example' }),
    ).toBe('https://custom.example');
    expect(
      siteOriginFrom(
        { host: 'preview-abc.vercel.app' },
        { VERCEL_URL: 'preview-abc.vercel.app' },
      ),
    ).toBe('https://preview-abc.vercel.app');
    expect(siteOriginFrom({ host: '127.0.0.1:3000' })).toBe('http://127.0.0.1:3000');
    expect(siteOriginFrom({ host: '[::1]:3000' })).toBe('http://[::1]:3000');
  });

  it('does not trust an arbitrary third-party vercel.app deployment', () => {
    expect(siteOriginFrom({ host: 'attacker-project.vercel.app' })).toBe(CANONICAL_SITE_ORIGIN);
  });

  it('rejects malformed and injected host values', () => {
    const injected = [
      'evil.example/phish',
      'evil.example:80/steal',
      'user@evil.example',
      'evil.example\r\nX-Injected: 1',
      'https://evil.example',
      'evil.example:abc',
      'flinttrade.vercel.app.attacker.example',
      '127.0.0.1.attacker.example',
      'vercel.app',
      '.vercel.app',
    ];

    for (const host of injected) {
      expect(siteOriginFrom({ host }), host).toBe(CANONICAL_SITE_ORIGIN);
    }
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
