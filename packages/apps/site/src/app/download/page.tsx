import { ArrowRight, Download, ExternalLink, FileArchive, RefreshCw, ShieldCheck, Terminal } from 'lucide-react';
import Link from 'next/link';

import { SiteFooter } from '@/components/site-footer';
import { SiteHeader } from '@/components/site-header';
import {
  DEFAULT_DESKTOP_RELEASE,
  GITHUB_RELEASES_URL,
  assetForPlatform,
  formatBytes,
  platformLabel,
  type DesktopReleaseAsset,
  type DesktopReleaseManifest,
  type GitHubRelease,
  selectDesktopRelease,
} from '@/lib/desktop-release';

export const revalidate = 300;

export const metadata = {
  title: 'Download',
  description:
    'Download FlintTrade desktop installers for macOS, Windows, and Linux, or use the one-command installer wrapper.',
};

const guarantees = [
  {
    icon: Download,
    title: 'Installer-first',
    copy: 'Download a ready desktop package for your OS. The one-command scripts use the same release assets by default.',
  },
  {
    icon: FileArchive,
    title: 'Bundled app',
    copy: 'The desktop package includes the FlintTrade backend sidecar and terminal UI, so there is no separate server to start.',
  },
  {
    icon: RefreshCw,
    title: 'Update path',
    copy: 'Re-run the installer command or use Settings → Updates in the desktop app to fetch the matching release installer.',
  },
  {
    icon: ShieldCheck,
    title: 'Honest beta',
    copy: 'Current beta installers are unsigned. macOS may require right-click → Open; Windows may show SmartScreen.',
  },
];

const platforms = [
  {
    platform: 'macOS (Apple Silicon & Intel)',
    command: 'curl -fsSL https://flinttrade.vercel.app/install.sh | bash',
    needs: 'Downloads the matching .dmg release asset, copies FlintTrade.app, and launches it.',
  },
  {
    platform: 'Linux (x64 & arm64)',
    command: 'curl -fsSL https://flinttrade.vercel.app/install.sh | bash',
    needs: 'Downloads the matching AppImage by default; pass --package deb or --package rpm for native packages.',
  },
  {
    platform: 'Windows 10/11 (x64)',
    command: 'irm https://flinttrade.vercel.app/install.ps1 | iex',
    needs: 'Downloads and runs the NSIS setup .exe release asset.',
  },
];

function primaryDownloadsFor(manifest: DesktopReleaseManifest) {
  return [
    {
      title: 'macOS Apple Silicon',
      asset: assetForPlatform(manifest, 'macos', 'arm64'),
    },
    {
      title: 'macOS Intel',
      asset: assetForPlatform(manifest, 'macos', 'x64'),
    },
    {
      title: 'Windows 10/11',
      asset: assetForPlatform(manifest, 'windows', 'x64'),
    },
    {
      title: 'Linux x64 AppImage',
      asset: assetForPlatform(manifest, 'linux', 'x64', ['appimage']),
    },
    {
      title: 'Linux ARM64 AppImage',
      asset: assetForPlatform(manifest, 'linux', 'arm64', ['appimage']),
    },
  ].filter((entry): entry is { title: string; asset: DesktopReleaseAsset } => entry.asset != null);
}

async function releaseForDownloadPage(): Promise<DesktopReleaseManifest> {
  try {
    const response = await fetch(GITHUB_RELEASES_URL, {
      headers: {
        Accept: 'application/vnd.github+json',
        'User-Agent': 'flinttrade-site/download-page',
      },
      next: { revalidate: 300 },
    });
    if (!response.ok) return DEFAULT_DESKTOP_RELEASE;
    const releases = (await response.json()) as GitHubRelease[];
    return selectDesktopRelease(releases, { channel: 'beta' }) ?? DEFAULT_DESKTOP_RELEASE;
  } catch {
    return DEFAULT_DESKTOP_RELEASE;
  }
}

export default async function DownloadPage() {
  const manifest = await releaseForDownloadPage();
  const primaryDownloads = primaryDownloadsFor(manifest);

  return (
    <main className="site-shell">
      <SiteHeader />
      <section className="subpage">
        <h1>Download FlintTrade Desktop.</h1>
        <p>
          FlintTrade ships as installable desktop packages for macOS, Windows, and Linux. The
          current beta release is{' '}
          <span className="font-mono">{manifest.tag}</span>; it bundles the backend sidecar and
          the terminal UI into one app, with no separate server to run. Prefer the full asset list?
          Open the{' '}
          <a href={manifest.html_url} target="_blank" rel="noopener noreferrer">
            GitHub release
          </a>
          .
        </p>

        {primaryDownloads.length === 0 && (
          <p>
            Live release data is momentarily unavailable — grab the installer for your
            platform straight from the{' '}
            <a href={manifest.html_url} target="_blank" rel="noopener noreferrer">
              GitHub releases page
            </a>
            .
          </p>
        )}
        <div className="feature-grid">
          {primaryDownloads.map((entry) => (
            <article className="feature-card" key={entry.asset.name}>
              <Download aria-hidden="true" />
              <h3>{entry.title}</h3>
              <p>
                {platformLabel(entry.asset)} · {formatBytes(entry.asset.size)}
              </p>
              <a className="button primary" href={entry.asset.url}>
                Download <ArrowRight aria-hidden="true" size={17} />
              </a>
            </article>
          ))}
        </div>

        <h2>One-command install</h2>
        <p>
          These commands now download and install the matching release asset by default. Use
          <span className="font-mono"> --build-from-source</span> only when you intentionally want
          a local developer build with Rust, Node, Python, and Tauri system dependencies.
        </p>
        <div className="stack">
          {platforms.map((entry) => (
            <div className="code-panel" key={entry.platform}>
              <header>
                <span>{entry.platform}</span>
                <span>terminal</span>
              </header>
              <pre>
                <code>{entry.command}</code>
              </pre>
              <p className="code-panel-note">Needs: {entry.needs}</p>
            </div>
          ))}
        </div>

        <h2>All installer assets</h2>
        <div className="stack">
          {manifest.assets.map((asset) => (
            <div className="code-panel" key={asset.name}>
              <header>
                <span>{platformLabel(asset)}</span>
                <span>{formatBytes(asset.size)}</span>
              </header>
              <pre>
                <code>{asset.name}</code>
              </pre>
              <p className="code-panel-note">
                <a href={asset.url}>Download this asset</a>
              </p>
            </div>
          ))}
        </div>

        <div className="feature-grid">
          {guarantees.map((item) => {
            const Icon = item.icon;
            return (
              <article className="feature-card" key={item.title}>
                <Icon aria-hidden="true" />
                <h3>{item.title}</h3>
                <p>{item.copy}</p>
              </article>
            );
          })}
        </div>

        <h2>Build from source</h2>
        <p>
          The source-build path remains available for contributors and operators who want to audit
          and compile the app locally. It needs Rust, Node 22+, pnpm 9, Python 3.12 with uv,
          PyInstaller, and platform-specific Tauri build tools such as Xcode Command Line Tools,
          Visual Studio Build Tools, or WebKitGTK development libraries.
        </p>

        <div className="section-actions">
          <Link className="button primary" href="/docs/desktop">
            Desktop guide (what the app bundles) <ArrowRight aria-hidden="true" size={17} />
          </Link>
          <a className="button secondary" href="/api/desktop-release">
            Release manifest <Terminal aria-hidden="true" size={17} />
          </a>
          <a
            className="button secondary"
            href="https://github.com/navaneeshnagarajan/FlintTrade/blob/main/scripts/install/flinttrade-install.sh"
            target="_blank"
            rel="noopener noreferrer"
          >
            Read the install script <ExternalLink aria-hidden="true" size={17} />
          </a>
        </div>

        <p className="hero-disclaimer">
          {manifest.tag} is not production ready. Use Explore and Practice modes first; Live mode
          remains your own risk.
        </p>
      </section>
      <SiteFooter />
    </main>
  );
}
