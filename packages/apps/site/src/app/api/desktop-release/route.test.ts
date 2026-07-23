import { afterEach, describe, expect, it, vi } from 'vitest';

import { FIXTURE_DESKTOP_RELEASE, FIXTURE_GITHUB_RELEASE } from '../../../lib/desktop-release.fixtures';
import { GITHUB_RELEASES_URL } from '../../../lib/desktop-release';
import { GET, OPTIONS } from './route';

const stableWithoutDesktopAssets = {
  tag_name: 'v0.5.1',
  prerelease: false,
  draft: false,
  published_at: '2026-05-20T00:14:37Z',
  html_url: 'https://github.com/navaneeshnagarajan/FlintTrade/releases/tag/v0.5.1',
  assets: [],
};

describe('/api/desktop-release', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('derives the beta Electron release, digests and checksum URL from one GitHub API response', async () => {
    const fetchMock = vi.fn(async () =>
      Response.json([stableWithoutDesktopAssets, FIXTURE_GITHUB_RELEASE]),
    );
    vi.stubGlobal('fetch', fetchMock);

    const response = await GET(
      new Request('https://flinttrade.vercel.app/api/desktop-release?channel=beta'),
    );
    const release = await response.json();

    expect(response.status).toBe(200);
    expect(response.headers.get('Access-Control-Allow-Origin')).toBe('*');
    expect(release).toEqual(FIXTURE_DESKTOP_RELEASE);
    expect(release.assets).toHaveLength(4);
    expect(release.assets.every((asset: { sha256?: string }) => /^[a-f0-9]{64}$/.test(asset.sha256 ?? ''))).toBe(
      true,
    );
    expect(release.checksum_url).toMatch(/\/v9\.9\.9-beta\.test\/SHA256SUMS\.txt$/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(GITHUB_RELEASES_URL, expect.any(Object));
  });

  it('does not fetch or trust the retired uploaded desktop manifest', async () => {
    const legacyManifestUrl =
      'https://github.com/navaneeshnagarajan/FlintTrade/releases/download/v9.9.9-beta.test/flinttrade-desktop-manifest.json';
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) !== GITHUB_RELEASES_URL) {
        throw new Error(`unexpected second fetch: ${String(input)}`);
      }
      return Response.json([
        {
          ...FIXTURE_GITHUB_RELEASE,
          assets: [
            ...(FIXTURE_GITHUB_RELEASE.assets ?? []),
            {
              name: 'flinttrade-desktop-manifest.json',
              size: 1024,
              browser_download_url: legacyManifestUrl,
            },
          ],
        },
      ]);
    });
    vi.stubGlobal('fetch', fetchMock);

    const response = await GET(
      new Request('https://flinttrade.vercel.app/api/desktop-release?channel=beta'),
    );

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(await response.json()).toEqual(FIXTURE_DESKTOP_RELEASE);
  });

  it('does not fall back to beta when stable has no complete Electron release', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json([stableWithoutDesktopAssets, FIXTURE_GITHUB_RELEASE])),
    );

    const response = await GET(
      new Request('https://flinttrade.vercel.app/api/desktop-release?channel=stable'),
    );
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body.error).toMatch(/No desktop installer release/i);
  });

  it('fails closed when GitHub release lookup fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('rate limited', { status: 429 })));

    const response = await GET(
      new Request('https://flinttrade.vercel.app/api/desktop-release?channel=beta'),
    );
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(response.headers.get('Access-Control-Allow-Origin')).toBe('*');
    expect(body.error).toMatch(/HTTP 429/);
  });

  it('serves CORS preflight for installer clients', async () => {
    const response = await OPTIONS();

    expect(response.status).toBe(204);
    expect(response.headers.get('Access-Control-Allow-Origin')).toBe('*');
    expect(response.headers.get('Access-Control-Allow-Methods')).toContain('GET');
  });
});
