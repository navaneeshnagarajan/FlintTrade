import { afterEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_DESKTOP_RELEASE, DESKTOP_RELEASE_MANIFEST_ASSET } from '../../../lib/desktop-release';
import { GET, OPTIONS } from './route';

const betaRelease = {
  tag_name: DEFAULT_DESKTOP_RELEASE.tag,
  prerelease: true,
  draft: false,
  published_at: DEFAULT_DESKTOP_RELEASE.published_at,
  html_url: DEFAULT_DESKTOP_RELEASE.html_url,
  assets: DEFAULT_DESKTOP_RELEASE.assets.map((asset) => ({
    name: asset.name,
    size: asset.size,
    browser_download_url: asset.url,
  })),
};

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

  it('returns the beta desktop release assets instead of relying on GitHub latest stable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json([stableWithoutDesktopAssets, betaRelease])),
    );

    const response = await GET(new Request('https://flinttrade.vercel.app/api/desktop-release?channel=beta'));
    const manifest = await response.json();

    expect(response.status).toBe(200);
    expect(response.headers.get('Access-Control-Allow-Origin')).toBe('*');
    expect(manifest.tag).toBe(DEFAULT_DESKTOP_RELEASE.tag);
    expect(manifest.assets).toHaveLength(9);
    expect(manifest.assets).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ os: 'macos', kind: 'dmg' }),
        expect.objectContaining({ os: 'windows', kind: 'nsis' }),
        expect.objectContaining({ os: 'linux', kind: 'appimage' }),
      ]),
    );
  });

  it('uses the uploaded desktop manifest when present so checksums reach clients', async () => {
    const manifestAssetUrl = 'https://downloads.example.invalid/flinttrade-desktop-manifest.json';
    const manifestWithChecksums = {
      ...DEFAULT_DESKTOP_RELEASE,
      assets: DEFAULT_DESKTOP_RELEASE.assets.map((asset, index) => ({
        ...asset,
        sha256: `${index}`.repeat(64).slice(0, 64).padEnd(64, 'a'),
      })),
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === manifestAssetUrl) return Response.json(manifestWithChecksums);
      return Response.json([
        stableWithoutDesktopAssets,
        {
          ...betaRelease,
          assets: [
            ...betaRelease.assets,
            {
              name: DESKTOP_RELEASE_MANIFEST_ASSET,
              size: 1024,
              browser_download_url: manifestAssetUrl,
            },
          ],
        },
      ]);
    });
    vi.stubGlobal('fetch', fetchMock);

    const response = await GET(new Request('https://flinttrade.vercel.app/api/desktop-release?channel=beta'));
    const manifest = await response.json();

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledWith(manifestAssetUrl, expect.any(Object));
    expect(manifest.assets[0].sha256).toMatch(/^[a-f0-9]{64}$/i);
  });

  it('fails closed when a published desktop manifest asset is invalid', async () => {
    const manifestAssetUrl = 'https://downloads.example.invalid/flinttrade-desktop-manifest.json';
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input) === manifestAssetUrl) return Response.json({ tag: DEFAULT_DESKTOP_RELEASE.tag, assets: [] });
        return Response.json([
          {
            ...betaRelease,
            assets: [
              ...betaRelease.assets,
              {
                name: DESKTOP_RELEASE_MANIFEST_ASSET,
                size: 1024,
                browser_download_url: manifestAssetUrl,
              },
            ],
          },
        ]);
      }),
    );

    const response = await GET(new Request('https://flinttrade.vercel.app/api/desktop-release?channel=beta'));
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body.error).toMatch(/Published desktop manifest/i);
  });

  it('does not fall back to beta when the stable channel has no desktop installers', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json([stableWithoutDesktopAssets, betaRelease])),
    );

    const response = await GET(new Request('https://flinttrade.vercel.app/api/desktop-release?channel=stable'));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body.error).toMatch(/No desktop installer release/i);
  });

  it('fails closed when GitHub release lookup fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('rate limited', { status: 429 })));

    const response = await GET(new Request('https://flinttrade.vercel.app/api/desktop-release?channel=beta'));
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
