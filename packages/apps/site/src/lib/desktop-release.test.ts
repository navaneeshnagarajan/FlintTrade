import { describe, expect, it } from 'vitest';

import {
  DEFAULT_DESKTOP_RELEASE,
  assetForPlatform,
  formatBytes,
  manifestFromGitHubRelease,
  parseDesktopReleaseAsset,
  selectDesktopRelease,
} from './desktop-release';

const betaAssets = DEFAULT_DESKTOP_RELEASE.assets.map((asset) => ({
  name: asset.name,
  size: asset.size,
  browser_download_url: asset.url,
}));

describe('desktop release asset parsing', () => {
  it('normalises every current beta installer asset', () => {
    const parsed = betaAssets.map(parseDesktopReleaseAsset);
    expect(parsed).toHaveLength(9);
    expect(parsed).not.toContain(null);
    expect(parsed).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ os: 'macos', arch: 'arm64', kind: 'dmg' }),
        expect.objectContaining({ os: 'macos', arch: 'x64', kind: 'dmg' }),
        expect.objectContaining({ os: 'windows', arch: 'x64', kind: 'nsis' }),
        expect.objectContaining({ os: 'linux', arch: 'x64', kind: 'appimage' }),
        expect.objectContaining({ os: 'linux', arch: 'arm64', kind: 'appimage' }),
        expect.objectContaining({ os: 'linux', arch: 'x64', kind: 'deb' }),
        expect.objectContaining({ os: 'linux', arch: 'arm64', kind: 'rpm' }),
      ]),
    );
  });

  it('ignores source archives and checksum assets', () => {
    expect(
      parseDesktopReleaseAsset({
        name: 'Source code.zip',
        browser_download_url: 'https://example.invalid/source.zip',
      }),
    ).toBeNull();
    expect(
      parseDesktopReleaseAsset({
        name: 'SHA256SUMS.txt',
        browser_download_url: 'https://example.invalid/SHA256SUMS.txt',
      }),
    ).toBeNull();
  });
});

describe('desktop release selection', () => {
  const beta = {
    tag_name: 'v0.6.0-beta.1',
    prerelease: true,
    draft: false,
    published_at: '2026-07-02T19:43:54Z',
    html_url: 'https://github.com/navaneeshnagarajan/FlintTrade/releases/tag/v0.6.0-beta.1',
    assets: betaAssets,
  };
  const oldStableWithoutInstallers = {
    tag_name: 'v0.5.1',
    prerelease: false,
    draft: false,
    published_at: '2026-05-20T00:14:37Z',
    html_url: 'https://github.com/navaneeshnagarajan/FlintTrade/releases/tag/v0.5.1',
    assets: [],
  };

  it('builds a manifest only when desktop installers exist', () => {
    expect(manifestFromGitHubRelease(oldStableWithoutInstallers)).toBeNull();
    expect(manifestFromGitHubRelease(beta)).toMatchObject({
      tag: 'v0.6.0-beta.1',
      version: '0.6.0-beta.1',
      channel: 'beta',
      prerelease: true,
      assets: expect.any(Array),
    });
  });

  it('selects prerelease desktop assets for the beta channel instead of GitHub latest stable', () => {
    const selected = selectDesktopRelease([oldStableWithoutInstallers, beta], { channel: 'beta' });
    expect(selected?.tag).toBe('v0.6.0-beta.1');
    expect(selected?.assets).toHaveLength(9);
  });

  it('returns null for stable when no stable release has desktop assets', () => {
    expect(selectDesktopRelease([oldStableWithoutInstallers, beta], { channel: 'stable' })).toBeNull();
  });

  it('selects a requested tag with or without the leading v', () => {
    expect(selectDesktopRelease([beta], { tag: '0.6.0-beta.1' })?.tag).toBe('v0.6.0-beta.1');
    expect(selectDesktopRelease([beta], { tag: 'v0.6.0-beta.1' })?.tag).toBe('v0.6.0-beta.1');
  });
});

describe('desktop release platform lookup', () => {
  it('prefers AppImage for Linux script installs', () => {
    expect(assetForPlatform(DEFAULT_DESKTOP_RELEASE, 'linux', 'x64')?.kind).toBe('appimage');
  });

  it('can request native Linux packages explicitly', () => {
    expect(assetForPlatform(DEFAULT_DESKTOP_RELEASE, 'linux', 'arm64', ['deb'])?.name).toMatch(/arm64\.deb$/);
    expect(assetForPlatform(DEFAULT_DESKTOP_RELEASE, 'linux', 'x64', ['rpm'])?.name).toMatch(/x86_64\.rpm$/);
  });

  it('formats asset sizes for UI labels', () => {
    expect(formatBytes(208530715)).toBe('199 MB');
  });
});
