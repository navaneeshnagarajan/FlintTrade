import { describe, expect, it } from 'vitest';

import { FIXTURE_DESKTOP_RELEASE, FIXTURE_GITHUB_RELEASE } from './desktop-release.fixtures';
import {
  TRUSTED_ASSET_URL_PREFIX,
  assetForPlatform,
  formatBytes,
  isDesktopReleaseManifest,
  isTrustedAssetUrl,
  manifestFromGitHubRelease,
  parseDesktopReleaseAsset,
  platformLabel,
  releaseChannelLabel,
  selectDesktopRelease,
  sha256FromDigest,
} from './desktop-release';

const REPO_RELEASE = `${TRUSTED_ASSET_URL_PREFIX}v9.9.9-beta.test`;

function releaseAt(version: string, prerelease: boolean, publishedAt: string) {
  const sourceVersion = FIXTURE_DESKTOP_RELEASE.version;
  const tag = `v${version}`;
  return {
    ...FIXTURE_GITHUB_RELEASE,
    tag_name: tag,
    prerelease,
    published_at: publishedAt,
    html_url: `https://github.com/navaneeshnagarajan/FlintTrade/releases/tag/${tag}`,
    assets: FIXTURE_GITHUB_RELEASE.assets?.map((asset) => ({
      ...asset,
      name: asset.name?.replaceAll(sourceVersion, version),
      browser_download_url: asset.browser_download_url?.replaceAll(sourceVersion, version),
    })),
  };
}

describe('Electron desktop release asset parsing', () => {
  it('normalises exactly the four current Electron installer kinds', () => {
    const parsed = (FIXTURE_GITHUB_RELEASE.assets ?? []).map(parseDesktopReleaseAsset);

    expect(parsed.filter((asset) => asset != null)).toEqual(FIXTURE_DESKTOP_RELEASE.assets);
    expect(parsed.filter((asset) => asset != null)).toEqual([
      expect.objectContaining({ os: 'macos', arch: 'universal', kind: 'dmg' }),
      expect.objectContaining({ os: 'windows', arch: 'x64', kind: 'nsis' }),
      expect.objectContaining({ os: 'linux', arch: 'x64', kind: 'appimage' }),
      expect.objectContaining({ os: 'linux', arch: 'arm64', kind: 'appimage' }),
    ]);
  });

  it.each([
    'FlintTrade_9.9.9-beta.test_aarch64.dmg',
    'FlintTrade_9.9.9-beta.test_x64-setup.exe',
    'FlintTrade_9.9.9-beta.test_amd64.AppImage',
    'FlintTrade-9.9.9-beta.test-mac-universal.zip',
    'FlintTrade-9.9.9-beta.test-linux-x64.deb',
    'FlintTrade-9.9.9-beta.test-linux-arm64.rpm',
    'flinttrade-desktop-manifest.json',
    'latest.json',
    'SHA256SUMS.txt',
  ])('ignores legacy, updater, checksum and non-installer asset %s', (name) => {
    expect(
      parseDesktopReleaseAsset({
        name,
        browser_download_url: `${REPO_RELEASE}/${name}`,
      }),
    ).toBeNull();
  });

  it('refuses an installer asset outside the official release path', () => {
    expect(
      parseDesktopReleaseAsset({
        name: 'FlintTrade-9.9.9-beta.test-win-x64.exe',
        browser_download_url: 'https://evil.example/FlintTrade-9.9.9-beta.test-win-x64.exe',
      }),
    ).toBeNull();
  });

  it('surfaces a valid GitHub asset digest as a bare lowercase SHA-256', () => {
    const hex = 'b'.repeat(64);
    const parsed = parseDesktopReleaseAsset({
      name: 'FlintTrade-9.9.9-beta.test-win-x64.exe',
      browser_download_url: `${REPO_RELEASE}/FlintTrade-9.9.9-beta.test-win-x64.exe`,
      digest: `sha256:${hex.toUpperCase()}`,
    });

    expect(parsed?.sha256).toBe(hex);
  });

  it('omits SHA-256 when GitHub provides no digest or a malformed digest', () => {
    const base = {
      name: 'FlintTrade-9.9.9-beta.test-win-x64.exe',
      browser_download_url: `${REPO_RELEASE}/FlintTrade-9.9.9-beta.test-win-x64.exe`,
    };

    expect(parseDesktopReleaseAsset(base)?.sha256).toBeUndefined();
    expect(parseDesktopReleaseAsset({ ...base, digest: 'md5:deadbeef' })?.sha256).toBeUndefined();
    expect(sha256FromDigest('sha256:tooshort')).toBeUndefined();
  });
});

describe('trusted release metadata', () => {
  it('accepts only the official repository release-download prefix', () => {
    expect(isTrustedAssetUrl(`${REPO_RELEASE}/x.dmg`)).toBe(true);
    expect(isTrustedAssetUrl('https://github.com/other/repo/releases/download/v1/x.dmg')).toBe(false);
    expect(isTrustedAssetUrl('https://evil.example/x.dmg')).toBe(false);
    expect(isTrustedAssetUrl('http://github.com/navaneeshnagarajan/FlintTrade/releases/download/v1/x.dmg')).toBe(false);
    expect(isTrustedAssetUrl(undefined)).toBe(false);
  });

  it('validates the generated API shape and its checksum URL', () => {
    expect(isDesktopReleaseManifest(FIXTURE_DESKTOP_RELEASE)).toBe(true);
    expect(
      isDesktopReleaseManifest({
        ...FIXTURE_DESKTOP_RELEASE,
        checksum_url: 'https://evil.example/SHA256SUMS.txt',
      }),
    ).toBe(false);
    expect(
      isDesktopReleaseManifest({
        ...FIXTURE_DESKTOP_RELEASE,
        checksum_url: undefined,
      }),
    ).toBe(false);
  });

  it('rejects metadata carrying an untrusted installer URL', () => {
    const tampered = {
      ...FIXTURE_DESKTOP_RELEASE,
      assets: FIXTURE_DESKTOP_RELEASE.assets.map((asset, index) =>
        index === 0 ? { ...asset, url: 'https://evil.example/setup.exe' } : asset,
      ),
    };

    expect(isDesktopReleaseManifest(tampered)).toBe(false);
  });
});

describe('desktop release selection', () => {
  const oldStableWithoutInstallers = {
    tag_name: 'v0.5.1',
    prerelease: false,
    draft: false,
    published_at: '2026-05-20T00:14:37Z',
    html_url: 'https://github.com/navaneeshnagarajan/FlintTrade/releases/tag/v0.5.1',
    assets: [],
  };

  it('derives complete release metadata, hashes and checksum URL from one GitHub release object', () => {
    expect(manifestFromGitHubRelease(FIXTURE_GITHUB_RELEASE)).toEqual(FIXTURE_DESKTOP_RELEASE);
  });

  it('rejects an incomplete Electron installer set', () => {
    expect(
      manifestFromGitHubRelease({
        ...FIXTURE_GITHUB_RELEASE,
        assets: FIXTURE_GITHUB_RELEASE.assets?.slice(0, 3),
      }),
    ).toBeNull();
  });

  it('rejects a release without its exact same-release checksum asset', () => {
    expect(
      manifestFromGitHubRelease({
        ...FIXTURE_GITHUB_RELEASE,
        assets: FIXTURE_GITHUB_RELEASE.assets?.filter((asset) => asset.name !== 'SHA256SUMS.txt'),
      }),
    ).toBeNull();
  });

  it('ignores assets whose version or release-download tag does not match the release', () => {
    const assets = [...(FIXTURE_GITHUB_RELEASE.assets ?? [])];
    assets[0] = {
      ...assets[0],
      name: 'FlintTrade-9.9.8-beta.test-mac-universal.dmg',
      browser_download_url: `${REPO_RELEASE}/FlintTrade-9.9.8-beta.test-mac-universal.dmg`,
    };
    expect(manifestFromGitHubRelease({ ...FIXTURE_GITHUB_RELEASE, assets })).toBeNull();

    assets[0] = {
      ...(FIXTURE_GITHUB_RELEASE.assets ?? [])[0],
      browser_download_url:
        `${TRUSTED_ASSET_URL_PREFIX}v9.9.8-beta.test/FlintTrade-9.9.9-beta.test-mac-universal.dmg`,
    };
    expect(manifestFromGitHubRelease({ ...FIXTURE_GITHUB_RELEASE, assets })).toBeNull();
  });

  it('ignores draft and rolling updater releases even when they carry matching names', () => {
    expect(manifestFromGitHubRelease({ ...FIXTURE_GITHUB_RELEASE, draft: true })).toBeNull();
    expect(
      manifestFromGitHubRelease({
        ...FIXTURE_GITHUB_RELEASE,
        tag_name: 'updater-beta',
      }),
    ).toBeNull();
  });

  it('requires GitHub prerelease metadata to match the release tag in both directions', () => {
    expect(
      manifestFromGitHubRelease({
        ...FIXTURE_GITHUB_RELEASE,
        prerelease: false,
      }),
    ).toBeNull();
    expect(
      manifestFromGitHubRelease(releaseAt('10.0.0', true, '2026-07-01T00:00:00Z')),
    ).toBeNull();
  });

  it('selects prerelease Electron assets for beta instead of GitHub latest stable', () => {
    const selected = selectDesktopRelease([oldStableWithoutInstallers, FIXTURE_GITHUB_RELEASE], {
      channel: 'beta',
    });

    expect(selected).toEqual(FIXTURE_DESKTOP_RELEASE);
  });

  it('keeps beta off alpha, dev and rc while allowing a newer stable promotion', () => {
    const stable = releaseAt('10.0.0', false, '2026-04-01T00:00:00Z');
    const selected = selectDesktopRelease([
      releaseAt('11.0.0-alpha.1', true, '2026-07-01T00:00:00Z'),
      releaseAt('11.0.0-dev.1', true, '2026-06-01T00:00:00Z'),
      releaseAt('11.0.0-rc.1', true, '2026-05-01T00:00:00Z'),
      stable,
      FIXTURE_GITHUB_RELEASE,
    ], { channel: 'beta' });

    expect(selected?.tag).toBe('v10.0.0');
    expect(selected?.channel).toBe('stable');
    expect(manifestFromGitHubRelease(releaseAt('11.0.0-alpha.1', true, '2026-07-01T00:00:00Z'))).toBeNull();
  });

  it('returns null for stable when no stable release has a complete installer set', () => {
    expect(
      selectDesktopRelease([oldStableWithoutInstallers, FIXTURE_GITHUB_RELEASE], { channel: 'stable' }),
    ).toBeNull();
  });

  it('selects a requested tag with or without the leading v', () => {
    expect(selectDesktopRelease([FIXTURE_GITHUB_RELEASE], { tag: '9.9.9-beta.test' })?.tag).toBe(
      'v9.9.9-beta.test',
    );
    expect(selectDesktopRelease([FIXTURE_GITHUB_RELEASE], { tag: 'v9.9.9-beta.test' })?.tag).toBe(
      'v9.9.9-beta.test',
    );
  });
});

describe('desktop release platform lookup', () => {
  it('selects both Linux AppImage architectures', () => {
    expect(assetForPlatform(FIXTURE_DESKTOP_RELEASE, 'linux', 'x64')?.name).toMatch(/linux-x64\.AppImage$/);
    expect(assetForPlatform(FIXTURE_DESKTOP_RELEASE, 'linux', 'arm64')?.name).toMatch(
      /linux-arm64\.AppImage$/,
    );
  });

  it('labels universal macOS and formats compact shell asset sizes', () => {
    expect(platformLabel(FIXTURE_DESKTOP_RELEASE.assets[0])).toBe('macOS Universal .dmg');
    expect(formatBytes(18_000_000)).toBe('17 MB');
  });

  it('labels beta and stable promotion copy from the selected manifest', () => {
    expect(releaseChannelLabel(FIXTURE_DESKTOP_RELEASE)).toBe('beta');
    expect(releaseChannelLabel({ prerelease: false })).toBe('stable');
  });
});
