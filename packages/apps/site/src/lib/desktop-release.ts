export type DesktopReleaseChannel = 'beta' | 'stable';
export type DesktopOs = 'macos' | 'windows' | 'linux';
export type DesktopArch = 'x64' | 'arm64';
export type DesktopAssetKind = 'dmg' | 'nsis' | 'appimage' | 'deb' | 'rpm';

export interface DesktopReleaseAsset {
  os: DesktopOs;
  arch: DesktopArch;
  kind: DesktopAssetKind;
  name: string;
  size: number;
  url: string;
  sha256?: string;
}

export interface DesktopReleaseManifest {
  tag: string;
  version: string;
  channel: DesktopReleaseChannel;
  prerelease: boolean;
  published_at: string;
  html_url: string;
  assets: DesktopReleaseAsset[];
}

export interface GitHubReleaseAsset {
  name?: string;
  size?: number;
  browser_download_url?: string;
  /** GitHub's per-asset content digest, e.g. "sha256:<64 hex>", when present. */
  digest?: string;
}

/**
 * Asset downloads MUST originate from the official repository's release-download
 * path. The installer scripts fetch this URL and RUN the resulting installer, so
 * a manifest that smuggled an arbitrary host here would be remote code execution
 * on the operator's machine. Pinning the prefix (not just the host) also rejects
 * any other GitHub repo. `browser_download_url` from the GitHub API is always on
 * this prefix; the install scripts enforce the same check independently.
 */
export const TRUSTED_ASSET_URL_PREFIX =
  'https://github.com/navaneeshnagarajan/FlintTrade/releases/download/';

/** True only for an official-repo release-download URL. */
export function isTrustedAssetUrl(url: unknown): url is string {
  return typeof url === 'string' && url.startsWith(TRUSTED_ASSET_URL_PREFIX);
}

/** Extract a bare 64-hex sha256 from GitHub's "sha256:<hex>" digest field. */
export function sha256FromDigest(digest: string | undefined): string | undefined {
  if (!digest) return undefined;
  const match = /^sha256:([a-f0-9]{64})$/i.exec(digest.trim());
  return match ? match[1].toLowerCase() : undefined;
}

export interface GitHubRelease {
  tag_name?: string;
  prerelease?: boolean;
  draft?: boolean;
  published_at?: string;
  html_url?: string;
  assets?: GitHubReleaseAsset[];
}

export const GITHUB_RELEASES_URL =
  'https://api.github.com/repos/navaneeshnagarajan/FlintTrade/releases?per_page=20';

export const DESKTOP_RELEASE_REVALIDATE_SECONDS = 300;
export const DESKTOP_RELEASE_MANIFEST_ASSET = 'flinttrade-desktop-manifest.json';

export const DEFAULT_DESKTOP_RELEASE: DesktopReleaseManifest = {
  tag: 'v0.6.0-beta.1',
  version: '0.6.0-beta.1',
  channel: 'beta',
  prerelease: true,
  published_at: '2026-07-02T19:43:54Z',
  html_url: 'https://github.com/navaneeshnagarajan/FlintTrade/releases/tag/v0.6.0-beta.1',
  assets: [
    {
      os: 'linux',
      arch: 'arm64',
      kind: 'rpm',
      name: 'FlintTrade-0.6.0-beta.1-1.aarch64.rpm',
      size: 240093625,
      url: 'https://github.com/navaneeshnagarajan/FlintTrade/releases/download/v0.6.0-beta.1/FlintTrade-0.6.0-beta.1-1.aarch64.rpm',
    },
    {
      os: 'linux',
      arch: 'x64',
      kind: 'rpm',
      name: 'FlintTrade-0.6.0-beta.1-1.x86_64.rpm',
      size: 248806540,
      url: 'https://github.com/navaneeshnagarajan/FlintTrade/releases/download/v0.6.0-beta.1/FlintTrade-0.6.0-beta.1-1.x86_64.rpm',
    },
    {
      os: 'linux',
      arch: 'arm64',
      kind: 'appimage',
      name: 'FlintTrade_0.6.0-beta.1_aarch64.AppImage',
      size: 316230152,
      url: 'https://github.com/navaneeshnagarajan/FlintTrade/releases/download/v0.6.0-beta.1/FlintTrade_0.6.0-beta.1_aarch64.AppImage',
    },
    {
      os: 'macos',
      arch: 'arm64',
      kind: 'dmg',
      name: 'FlintTrade_0.6.0-beta.1_aarch64.dmg',
      size: 106866441,
      url: 'https://github.com/navaneeshnagarajan/FlintTrade/releases/download/v0.6.0-beta.1/FlintTrade_0.6.0-beta.1_aarch64.dmg',
    },
    {
      os: 'linux',
      arch: 'x64',
      kind: 'appimage',
      name: 'FlintTrade_0.6.0-beta.1_amd64.AppImage',
      size: 326593016,
      url: 'https://github.com/navaneeshnagarajan/FlintTrade/releases/download/v0.6.0-beta.1/FlintTrade_0.6.0-beta.1_amd64.AppImage',
    },
    {
      os: 'linux',
      arch: 'x64',
      kind: 'deb',
      name: 'FlintTrade_0.6.0-beta.1_amd64.deb',
      size: 248805568,
      url: 'https://github.com/navaneeshnagarajan/FlintTrade/releases/download/v0.6.0-beta.1/FlintTrade_0.6.0-beta.1_amd64.deb',
    },
    {
      os: 'linux',
      arch: 'arm64',
      kind: 'deb',
      name: 'FlintTrade_0.6.0-beta.1_arm64.deb',
      size: 240089914,
      url: 'https://github.com/navaneeshnagarajan/FlintTrade/releases/download/v0.6.0-beta.1/FlintTrade_0.6.0-beta.1_arm64.deb',
    },
    {
      os: 'windows',
      arch: 'x64',
      kind: 'nsis',
      name: 'FlintTrade_0.6.0-beta.1_x64-setup.exe',
      size: 208530715,
      url: 'https://github.com/navaneeshnagarajan/FlintTrade/releases/download/v0.6.0-beta.1/FlintTrade_0.6.0-beta.1_x64-setup.exe',
    },
    {
      os: 'macos',
      arch: 'x64',
      kind: 'dmg',
      name: 'FlintTrade_0.6.0-beta.1_x64.dmg',
      size: 115796291,
      url: 'https://github.com/navaneeshnagarajan/FlintTrade/releases/download/v0.6.0-beta.1/FlintTrade_0.6.0-beta.1_x64.dmg',
    },
  ],
};

export function parseDesktopReleaseAsset(asset: GitHubReleaseAsset): DesktopReleaseAsset | null {
  const name = asset.name ?? '';
  const url = asset.browser_download_url ?? '';
  // Refuse to surface any asset whose download URL is not on the official
  // repository's release path — the installer runs what this URL points to.
  if (!name || !isTrustedAssetUrl(url)) return null;

  const size = asset.size ?? 0;
  const sha256 = sha256FromDigest(asset.digest);
  const withDigest = <T extends DesktopReleaseAsset>(base: T): T =>
    sha256 ? { ...base, sha256 } : base;
  if (/\.dmg$/i.test(name)) {
    const arch = /_(?:aarch64|arm64)\.dmg$/i.test(name) ? 'arm64' : 'x64';
    return withDigest({ os: 'macos', arch, kind: 'dmg', name, size, url });
  }
  if (/_x64-setup\.exe$/i.test(name)) {
    return withDigest({ os: 'windows', arch: 'x64', kind: 'nsis', name, size, url });
  }
  if (/\.AppImage$/i.test(name)) {
    const arch = /_(?:aarch64|arm64)\.AppImage$/i.test(name) ? 'arm64' : 'x64';
    return withDigest({ os: 'linux', arch, kind: 'appimage', name, size, url });
  }
  if (/\.deb$/i.test(name)) {
    const arch = /_(?:aarch64|arm64)\.deb$/i.test(name) ? 'arm64' : 'x64';
    return withDigest({ os: 'linux', arch, kind: 'deb', name, size, url });
  }
  if (/\.rpm$/i.test(name)) {
    const arch = /\.(?:aarch64|arm64)\.rpm$/i.test(name) ? 'arm64' : 'x64';
    return withDigest({ os: 'linux', arch, kind: 'rpm', name, size, url });
  }
  return null;
}

export function releaseManifestAssetUrl(release: GitHubRelease): string | null {
  const asset = (release.assets ?? []).find((candidate) => candidate.name === DESKTOP_RELEASE_MANIFEST_ASSET);
  return asset?.browser_download_url ?? null;
}

export function isDesktopReleaseManifest(value: unknown): value is DesktopReleaseManifest {
  if (value == null || typeof value !== 'object') return false;
  const manifest = value as Partial<DesktopReleaseManifest>;
  if (typeof manifest.tag !== 'string' || !manifest.tag.startsWith('v')) return false;
  if (typeof manifest.version !== 'string') return false;
  if (manifest.channel !== 'beta' && manifest.channel !== 'stable') return false;
  if (typeof manifest.prerelease !== 'boolean') return false;
  if (typeof manifest.published_at !== 'string') return false;
  if (typeof manifest.html_url !== 'string') return false;
  if (!Array.isArray(manifest.assets) || manifest.assets.length === 0) return false;
  return manifest.assets.every((asset) => {
    if (asset == null || typeof asset !== 'object') return false;
    const candidate = asset as Partial<DesktopReleaseAsset>;
    return (
      (candidate.os === 'macos' || candidate.os === 'windows' || candidate.os === 'linux') &&
      (candidate.arch === 'x64' || candidate.arch === 'arm64') &&
      (candidate.kind === 'dmg' ||
        candidate.kind === 'nsis' ||
        candidate.kind === 'appimage' ||
        candidate.kind === 'deb' ||
        candidate.kind === 'rpm') &&
      typeof candidate.name === 'string' &&
      typeof candidate.size === 'number' &&
      isTrustedAssetUrl(candidate.url) &&
      (candidate.sha256 === undefined || /^[a-f0-9]{64}$/i.test(candidate.sha256))
    );
  });
}

export function manifestFromGitHubRelease(release: GitHubRelease): DesktopReleaseManifest | null {
  if (release.draft) return null;
  const tag = release.tag_name ?? '';
  if (!tag.startsWith('v')) return null;
  const assets = (release.assets ?? [])
    .map(parseDesktopReleaseAsset)
    .filter((asset): asset is DesktopReleaseAsset => asset != null)
    .sort(compareAssets);
  if (assets.length === 0) return null;
  const prerelease = Boolean(release.prerelease);
  return {
    tag,
    version: tag.replace(/^v/, ''),
    channel: prerelease ? 'beta' : 'stable',
    prerelease,
    published_at: release.published_at ?? '',
    html_url: release.html_url ?? `https://github.com/navaneeshnagarajan/FlintTrade/releases/tag/${tag}`,
    assets,
  };
}

export function selectDesktopRelease(
  releases: GitHubRelease[],
  options: { channel?: DesktopReleaseChannel; tag?: string } = {},
): DesktopReleaseManifest | null {
  const tag = options.tag?.trim();
  const manifests = releases
    .map(manifestFromGitHubRelease)
    .filter((manifest): manifest is DesktopReleaseManifest => manifest != null)
    .sort(compareManifestsNewestFirst);
  if (tag) {
    const normalised = tag.startsWith('v') ? tag : `v${tag}`;
    return manifests.find((manifest) => manifest.tag === normalised) ?? null;
  }
  const channel = options.channel ?? 'beta';
  if (channel === 'stable') {
    return manifests.find((manifest) => !manifest.prerelease) ?? null;
  }
  return manifests.find((manifest) => manifest.prerelease) ?? manifests[0] ?? null;
}

export function assetForPlatform(
  manifest: DesktopReleaseManifest,
  os: DesktopOs,
  arch: DesktopArch,
  preferredKinds?: DesktopAssetKind[],
): DesktopReleaseAsset | null {
  const fallbackKinds = defaultKindsForOs(os);
  const kinds = preferredKinds?.length ? preferredKinds : fallbackKinds;
  for (const kind of kinds) {
    const asset = manifest.assets.find((candidate) => {
      return candidate.os === os && candidate.arch === arch && candidate.kind === kind;
    });
    if (asset) return asset;
  }
  return null;
}

export function platformLabel(asset: Pick<DesktopReleaseAsset, 'os' | 'arch' | 'kind'>): string {
  const os = asset.os === 'macos' ? 'macOS' : asset.os === 'windows' ? 'Windows' : 'Linux';
  const arch = asset.arch === 'arm64' ? 'ARM64' : 'x64';
  const kind = asset.kind === 'nsis' ? 'setup .exe' : `.${asset.kind === 'appimage' ? 'AppImage' : asset.kind}`;
  return `${os} ${arch} ${kind}`;
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return 'unknown size';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}

function defaultKindsForOs(os: DesktopOs): DesktopAssetKind[] {
  if (os === 'macos') return ['dmg'];
  if (os === 'windows') return ['nsis'];
  return ['appimage', 'deb', 'rpm'];
}

function compareAssets(a: DesktopReleaseAsset, b: DesktopReleaseAsset): number {
  const osOrder = ['macos', 'windows', 'linux'];
  const kindOrder = ['dmg', 'nsis', 'appimage', 'deb', 'rpm'];
  return (
    osOrder.indexOf(a.os) - osOrder.indexOf(b.os) ||
    a.arch.localeCompare(b.arch) ||
    kindOrder.indexOf(a.kind) - kindOrder.indexOf(b.kind) ||
    a.name.localeCompare(b.name)
  );
}

function compareManifestsNewestFirst(a: DesktopReleaseManifest, b: DesktopReleaseManifest): number {
  const byDate = Date.parse(b.published_at) - Date.parse(a.published_at);
  if (Number.isFinite(byDate) && byDate !== 0) return byDate;
  return b.tag.localeCompare(a.tag);
}
