import { afterEach, describe, expect, it, vi } from 'vitest';

import { POST } from './route';

const validBody = JSON.stringify({
  'csp-report': {
    'blocked-uri': 'https://evil.example/script.js',
    'violated-directive': 'script-src',
    'document-uri': 'https://www.hosted.example/docs',
  },
});

function cspRequest(origin: string): Request {
  return new Request('https://hosted.example/api/csp-report', {
    method: 'POST',
    headers: {
      origin,
      'content-type': 'application/json',
    },
    body: validBody,
  });
}

describe('/api/csp-report', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('accepts reports from every configured site origin, not only the primary fallback', async () => {
    vi.stubEnv('FLINTTRADE_SITE_URL', 'https://hosted.example');
    vi.stubEnv('FLINTTRADE_SITE_ORIGINS', 'https://www.hosted.example');

    const response = await POST(cspRequest('https://www.hosted.example'));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true });
  });

  it('still accepts the primary configured origin', async () => {
    vi.stubEnv('FLINTTRADE_SITE_URL', 'https://hosted.example');
    vi.stubEnv('FLINTTRADE_SITE_ORIGINS', 'https://www.hosted.example');

    const response = await POST(cspRequest('https://hosted.example'));

    expect(response.status).toBe(200);
  });

  it('rejects a report from an origin that is not allow-listed', async () => {
    vi.stubEnv('FLINTTRADE_SITE_URL', 'https://hosted.example');
    vi.stubEnv('FLINTTRADE_SITE_ORIGINS', 'https://www.hosted.example');

    const response = await POST(cspRequest('https://evil.example'));

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ ok: false, reason: 'origin-mismatch' });
  });
});
