import { describe, expect, it } from 'vitest';

import {
  DEFAULT_DESKTOP_RELEASE,
  TRUSTED_ASSET_URL_PREFIX,
  assetForPlatform,
  formatBytes,
  isDesktopReleaseManifest,
  isTrustedAssetUrl,
  manifestFromGitHubRelease,
  parseDesktopReleaseAsset,
  selectDesktopRelease,
  sha256FromDigest,
} from './desktop-release';

const REPO_RELEASE = `${TRUSTED_ASSET_URL_PREFIX}v0.6.0-beta.1`;

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

  it('ignores source archives and checksum assets (official-repo URLs)', () => {
    expect(
      parseDesktopReleaseAsset({
        name: 'Source code.zip',
        browser_download_url: `${REPO_RELEASE}/source.zip`,
      }),
    ).toBeNull();
    expect(
      parseDesktopReleaseAsset({
        name: 'SHA256SUMS.txt',
        browser_download_url: `${REPO_RELEASE}/SHA256SUMS.txt`,
      }),
    ).toBeNull();
  });

  it('refuses an installer asset whose URL is not the official release path', () => {
    // A tampered manifest pointing a real installer name at an attacker host
    // must be rejected — the installer scripts RUN this file.
    expect(
      parseDesktopReleaseAsset({
        name: 'FlintTrade_0.6.0-beta.1_x64-setup.exe',
        browser_download_url: 'https://evil.example/FlintTrade_0.6.0-beta.1_x64-setup.exe',
      }),
    ).toBeNull();
    // A different GitHub repo is also refused (prefix pin, not just host).
    expect(
      parseDesktopReleaseAsset({
        name: 'FlintTrade_0.6.0-beta.1_x64.dmg',
        browser_download_url:
          'https://github.com/someone-else/evil/releases/download/v1/FlintTrade_0.6.0-beta.1_x64.dmg',
      }),
    ).toBeNull();
  });

  it('surfaces the GitHub asset digest as a bare sha256 so the installer can verify it', () => {
    const hex = 'a'.repeat(64);
    const parsed = parseDesktopReleaseAsset({
      name: 'FlintTrade_0.6.0-beta.1_x64-setup.exe',
      browser_download_url: `${REPO_RELEASE}/FlintTrade_0.6.0-beta.1_x64-setup.exe`,
      digest: `sha256:${hex.toUpperCase()}`,
    });
    expect(parsed?.sha256).toBe(hex);
  });

  it('omits sha256 when GitHub provides no (or a malformed) digest', () => {
    const base = {
      name: 'FlintTrade_0.6.0-beta.1_x64-setup.exe',
      browser_download_url: `${REPO_RELEASE}/FlintTrade_0.6.0-beta.1_x64-setup.exe`,
    };
    expect(parseDesktopReleaseAsset(base)?.sha256).toBeUndefined();
    expect(parseDesktopReleaseAsset({ ...base, digest: 'md5:deadbeef' })?.sha256).toBeUndefined();
    expect(sha256FromDigest('sha256:tooshort')).toBeUndefined();
  });
});

describe('trusted asset URL pinning', () => {
  it('accepts only the official repository release-download prefix', () => {
    expect(isTrustedAssetUrl(`${REPO_RELEASE}/x.dmg`)).toBe(true);
    expect(isTrustedAssetUrl('https://github.com/other/repo/releases/download/v1/x.dmg')).toBe(false);
    expect(isTrustedAssetUrl('https://evil.example/x.dmg')).toBe(false);
    expect(isTrustedAssetUrl('http://github.com/navaneeshnagarajan/FlintTrade/releases/download/v1/x.dmg')).toBe(false);
    expect(isTrustedAssetUrl(undefined)).toBe(false);
  });

  it('rejects a manifest carrying an untrusted asset URL', () => {
    const good = { ...DEFAULT_DESKTOP_RELEASE };
    expect(isDesktopReleaseManifest(good)).toBe(true);
    const tampered = {
      ...DEFAULT_DESKTOP_RELEASE,
      assets: DEFAULT_DESKTOP_RELEASE.assets.map((a, i) =>
        i === 0 ? { ...a, url: 'https://evil.example/setup.exe' } : a,
      ),
    };
    expect(isDesktopReleaseManifest(tampered)).toBe(false);
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
