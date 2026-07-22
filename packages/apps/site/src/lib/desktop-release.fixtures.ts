// Test-only release fixtures. The deliberately unreal version prevents these
// values from drifting against, or being mistaken for, a live release.
import type { DesktopReleaseManifest, GitHubRelease } from './desktop-release';

const releaseBase =
  'https://github.com/navaneeshnagarajan/FlintTrade/releases/download/v9.9.9-beta.test';

export const FIXTURE_DESKTOP_RELEASE: DesktopReleaseManifest = {
  tag: 'v9.9.9-beta.test',
  version: '9.9.9-beta.test',
  channel: 'beta',
  prerelease: true,
  published_at: '2026-01-01T00:00:00Z',
  html_url: 'https://github.com/navaneeshnagarajan/FlintTrade/releases/tag/v9.9.9-beta.test',
  checksum_url: `${releaseBase}/SHA256SUMS.txt`,
  assets: [
    {
      os: 'macos',
      arch: 'universal',
      kind: 'dmg',
      name: 'FlintTrade-9.9.9-beta.test-mac-universal.dmg',
      size: 18_000_000,
      url: `${releaseBase}/FlintTrade-9.9.9-beta.test-mac-universal.dmg`,
      sha256: '1'.repeat(64),
    },
    {
      os: 'windows',
      arch: 'x64',
      kind: 'nsis',
      name: 'FlintTrade-9.9.9-beta.test-win-x64.exe',
      size: 16_000_000,
      url: `${releaseBase}/FlintTrade-9.9.9-beta.test-win-x64.exe`,
      sha256: '2'.repeat(64),
    },
    {
      os: 'linux',
      arch: 'x64',
      kind: 'appimage',
      name: 'FlintTrade-9.9.9-beta.test-linux-x64.AppImage',
      size: 17_000_000,
      url: `${releaseBase}/FlintTrade-9.9.9-beta.test-linux-x64.AppImage`,
      sha256: '3'.repeat(64),
    },
    {
      os: 'linux',
      arch: 'arm64',
      kind: 'appimage',
      name: 'FlintTrade-9.9.9-beta.test-linux-arm64.AppImage',
      size: 17_500_000,
      url: `${releaseBase}/FlintTrade-9.9.9-beta.test-linux-arm64.AppImage`,
      sha256: '4'.repeat(64),
    },
  ],
};

export const FIXTURE_GITHUB_RELEASE: GitHubRelease = {
  tag_name: FIXTURE_DESKTOP_RELEASE.tag,
  prerelease: FIXTURE_DESKTOP_RELEASE.prerelease,
  draft: false,
  published_at: FIXTURE_DESKTOP_RELEASE.published_at,
  html_url: FIXTURE_DESKTOP_RELEASE.html_url,
  assets: [
    ...FIXTURE_DESKTOP_RELEASE.assets.map((asset) => ({
      name: asset.name,
      size: asset.size,
      browser_download_url: asset.url,
      digest: `sha256:${asset.sha256}`,
    })),
    {
      name: 'SHA256SUMS.txt',
      size: 512,
      browser_download_url: FIXTURE_DESKTOP_RELEASE.checksum_url,
      digest: `sha256:${'a'.repeat(64)}`,
    },
  ],
};
