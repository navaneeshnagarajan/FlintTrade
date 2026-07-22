export type DesktopReleaseChannel = 'beta' | 'stable';
export type DesktopOs = 'macos' | 'windows' | 'linux';
export type DesktopArch = 'x64' | 'arm64' | 'universal';
export type DesktopAssetKind = 'dmg' | 'nsis' | 'appimage';

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
  checksum_url?: string;
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
export const DESKTOP_RELEASE_CHECKSUM_ASSET = 'SHA256SUMS.txt';

import { APP_VERSION, APP_VERSION_TAG } from './version';

// Tag-agnostic fallback used only when the GitHub releases API is
// unreachable at request time. It intentionally pins NO asset links —
// hardcoded assets drift the moment a release ships (this block once served
// two-releases-stale downloads). The download page renders a "browse the
// release page" card when assets are empty.
export const DEFAULT_DESKTOP_RELEASE: DesktopReleaseManifest = {
  tag: APP_VERSION_TAG,
  version: APP_VERSION,
  channel: APP_VERSION.includes('-') ? 'beta' : 'stable',
  prerelease: APP_VERSION.includes('-'),
  published_at: '',
  html_url: 'https://github.com/navaneeshnagarajan/FlintTrade/releases',
  assets: [],
};

export function releaseChannelLabel(manifest: Pick<DesktopReleaseManifest, 'prerelease'>): 'beta' | 'stable' {
  return manifest.prerelease ? 'beta' : 'stable';
}

export function parseDesktopReleaseAsset(asset: GitHubReleaseAsset): DesktopReleaseAsset | null {
  const name = asset.name ?? '';
  const url = asset.browser_download_url ?? '';
  // Refuse to surface any asset whose download URL is not on the official
  // repository's release path — the installer runs what this URL points to.
  if (!name || !isTrustedAssetUrl(url)) return null;

  const identity = canonicalAssetIdentity(name);
  if (!identity) return null;

  const size = asset.size ?? 0;
  const sha256 = sha256FromDigest(asset.digest);
  const parsed: DesktopReleaseAsset = {
    os: identity.os,
    arch: identity.arch,
    kind: identity.kind,
    name,
    size,
    url,
  };
  return sha256 ? { ...parsed, sha256 } : parsed;
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
  if (!isTrustedAssetUrl(manifest.checksum_url)) return false;
  if (!Array.isArray(manifest.assets) || manifest.assets.length !== REQUIRED_ASSET_KEYS.length) return false;
  if (!isVersionTag(manifest.tag) || manifest.version !== manifest.tag.slice(1)) return false;
  const tag = manifest.tag;
  const version = manifest.version;
  const assetKeys = new Set<string>();
  const validAssets = manifest.assets.every((asset) => {
    if (asset == null || typeof asset !== 'object') return false;
    const candidate = asset as Partial<DesktopReleaseAsset>;
    if (typeof candidate.name !== 'string' || typeof candidate.size !== 'number') return false;
    const name = candidate.name;
    const identity = canonicalAssetIdentity(name);
    if (!identity || identity.version !== version) return false;
    const key = assetKey(identity);
    assetKeys.add(key);
    return (
      (candidate.os === 'macos' || candidate.os === 'windows' || candidate.os === 'linux') &&
      (candidate.arch === 'x64' || candidate.arch === 'arm64' || candidate.arch === 'universal') &&
      (candidate.kind === 'dmg' || candidate.kind === 'nsis' || candidate.kind === 'appimage') &&
      candidate.os === identity.os &&
      candidate.arch === identity.arch &&
      candidate.kind === identity.kind &&
      candidate.url === releaseAssetUrl(tag, name) &&
      (candidate.sha256 === undefined || /^[a-f0-9]{64}$/i.test(candidate.sha256))
    );
  });
  if (!validAssets || !REQUIRED_ASSET_KEYS.every((key) => assetKeys.has(key))) return false;
  return manifest.checksum_url === releaseAssetUrl(tag, DESKTOP_RELEASE_CHECKSUM_ASSET);
}

export function manifestFromGitHubRelease(release: GitHubRelease): DesktopReleaseManifest | null {
  if (release.draft) return null;
  const tag = release.tag_name ?? '';
  if (!isVersionTag(tag)) return null;
  const version = tag.slice(1);
  const assetsByKey = new Map<string, DesktopReleaseAsset>();
  for (const candidate of release.assets ?? []) {
    const parsed = parseDesktopReleaseAsset(candidate);
    if (!parsed) continue;
    const identity = canonicalAssetIdentity(parsed.name);
    if (!identity || identity.version !== version) continue;
    if (parsed.url !== releaseAssetUrl(tag, parsed.name)) continue;
    assetsByKey.set(assetKey(identity), parsed);
  }
  if (!REQUIRED_ASSET_KEYS.every((key) => assetsByKey.has(key))) return null;
  const assets = REQUIRED_ASSET_KEYS.map((key) => assetsByKey.get(key)!);
  const checksumUrl = checksumAssetUrl(release, tag);
  if (!checksumUrl) return null;
  const prerelease = Boolean(release.prerelease);
  const tagPrereleaseChannel = prereleaseChannel(version);
  if (prerelease !== (tagPrereleaseChannel !== null)) return null;
  if (prerelease && tagPrereleaseChannel !== 'beta') return null;
  return {
    tag,
    version,
    channel: prerelease ? 'beta' : 'stable',
    prerelease,
    published_at: release.published_at ?? '',
    html_url: release.html_url ?? `https://github.com/navaneeshnagarajan/FlintTrade/releases/tag/${tag}`,
    checksum_url: checksumUrl,
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
  return manifests[0] ?? null;
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
  const arch = asset.arch === 'universal' ? 'Universal' : asset.arch === 'arm64' ? 'ARM64' : 'x64';
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
  return ['appimage'];
}

interface CanonicalAssetIdentity {
  version: string;
  os: DesktopOs;
  arch: DesktopArch;
  kind: DesktopAssetKind;
}

const REQUIRED_ASSET_KEYS = [
  'macos:universal:dmg',
  'windows:x64:nsis',
  'linux:x64:appimage',
  'linux:arm64:appimage',
] as const;

function canonicalAssetIdentity(name: string): CanonicalAssetIdentity | null {
  const variants: Array<{
    pattern: RegExp;
    os: DesktopOs;
    arch: DesktopArch;
    kind: DesktopAssetKind;
  }> = [
    { pattern: /^FlintTrade-(.+)-mac-universal\.dmg$/, os: 'macos', arch: 'universal', kind: 'dmg' },
    { pattern: /^FlintTrade-(.+)-win-x64\.exe$/, os: 'windows', arch: 'x64', kind: 'nsis' },
    { pattern: /^FlintTrade-(.+)-linux-x64\.AppImage$/, os: 'linux', arch: 'x64', kind: 'appimage' },
    { pattern: /^FlintTrade-(.+)-linux-arm64\.AppImage$/, os: 'linux', arch: 'arm64', kind: 'appimage' },
  ];
  for (const variant of variants) {
    const match = variant.pattern.exec(name);
    if (match && isVersion(match[1])) {
      return {
        version: match[1],
        os: variant.os,
        arch: variant.arch,
        kind: variant.kind,
      };
    }
  }
  return null;
}

function assetKey(identity: Pick<CanonicalAssetIdentity, 'os' | 'arch' | 'kind'>): string {
  return `${identity.os}:${identity.arch}:${identity.kind}`;
}

function checksumAssetUrl(release: GitHubRelease, tag: string): string | null {
  const expected = releaseAssetUrl(tag, DESKTOP_RELEASE_CHECKSUM_ASSET);
  const checksum = (release.assets ?? []).find(
    (asset) => asset.name === DESKTOP_RELEASE_CHECKSUM_ASSET && asset.browser_download_url === expected,
  );
  return checksum ? expected : null;
}

function releaseAssetUrl(tag: string, name: string): string {
  return `${TRUSTED_ASSET_URL_PREFIX}${tag}/${name}`;
}

function isVersionTag(value: string): boolean {
  return value.startsWith('v') && isVersion(value.slice(1));
}

function isVersion(value: string): boolean {
  return /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?$/.test(value);
}

function prereleaseChannel(version: string): string | null {
  const separator = version.indexOf('-');
  if (separator < 0) return null;
  return version.slice(separator + 1).split('.')[0]?.toLowerCase() ?? null;
}

function compareManifestsNewestFirst(a: DesktopReleaseManifest, b: DesktopReleaseManifest): number {
  const byDate = Date.parse(b.published_at) - Date.parse(a.published_at);
  if (Number.isFinite(byDate) && byDate !== 0) return byDate;
  return b.tag.localeCompare(a.tag);
}
