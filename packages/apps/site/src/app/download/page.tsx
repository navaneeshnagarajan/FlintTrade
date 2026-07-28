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
  releaseChannelLabel,
  type DesktopReleaseAsset,
  type DesktopReleaseManifest,
  type GitHubRelease,
  selectDesktopRelease,
} from '@/lib/desktop-release';
import { siteSourceSha } from '@/lib/install-script-routes';

export const revalidate = 300;

export const metadata = {
  title: 'Download',
  description:
    'Check FlintTrade Electron installer availability for macOS, Windows, and Linux.',
};

const guarantees = [
  {
    icon: Download,
    title: 'Small Electron shell',
    copy: 'The release contains the native shell and bootstrap resources, while the application runtime stays as inspectable local source.',
  },
  {
    icon: FileArchive,
    title: 'Verified local runtime',
    copy: 'On first launch, the shell verifies pinned tools and builds hash-verified, integrity-locked local source before starting FlintTrade.',
  },
  {
    icon: RefreshCw,
    title: 'Two honest update paths',
    copy: 'Settings stages and health-checks source/runtime updates separately from the rarer Electron shell installer update.',
  },
  {
    icon: ShieldCheck,
    title: 'Verified release integrity',
    copy: 'One-command installs verify SHA-256 automatically. Direct downloads must be checked against the release SHA256SUMS.txt before opening.',
  },
];

const platforms = [
  {
    platform: 'macOS (Apple Silicon & Intel)',
    command: 'curl -fsSL https://flinttrade.vercel.app/install.sh | bash',
    needs: 'Downloads and verifies the universal DMG, installs FlintTrade.app, and launches the shell.',
  },
  {
    platform: 'Linux (x64 & arm64)',
    command: 'curl -fsSL https://flinttrade.vercel.app/install.sh | bash',
    needs: 'Downloads and verifies the matching AppImage, with an automatic no-FUSE fallback.',
  },
  {
    platform: 'Windows 10/11 (x64)',
    command: 'irm https://flinttrade.vercel.app/install.ps1 | iex',
    needs: 'Downloads and verifies the x64 NSIS setup before running the per-user installer.',
  },
];

function primaryDownloadsFor(manifest: DesktopReleaseManifest) {
  return [
    {
      title: 'macOS (Universal)',
      asset: assetForPlatform(manifest, 'macos', 'universal'),
    },
    {
      title: 'Windows 10/11',
      asset: assetForPlatform(manifest, 'windows', 'x64'),
    },
    // Linux is command-first: the install command below picks and verifies
    // the right AppImage for the machine, so no direct links are listed.
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
  const installerReleaseAvailable = manifest.assets.length > 0;
  const primaryDownloads = primaryDownloadsFor(manifest);
  const releaseChannel = releaseChannelLabel(manifest);
  const sourceSha = siteSourceSha();
  const installScriptSourceUrl = sourceSha === null
    ? null
    : `https://github.com/navaneeshnagarajan/FlintTrade/blob/${sourceSha}/scripts/install/flinttrade-install.sh`;

  return (
    <main className="site-shell">
      <SiteHeader />
      <section className="subpage">
        <h1>Download FlintTrade Desktop.</h1>
        {installerReleaseAvailable ? (
          <>
            <p>
              FlintTrade ships a small Electron shell for macOS, Windows, and Linux. The current{' '}
              {releaseChannel} release is <span className="font-mono">{manifest.tag}</span>. Its first
              launch verifies the required tools and builds the application runtime from locked local
              source. Prefer the full asset list? Open the{' '}
              <a href={manifest.html_url} target="_blank" rel="noopener noreferrer">
                GitHub release
              </a>
              .
            </p>

            {manifest.checksum_url ? (
              <p>
                The one-command installer below verifies SHA-256 automatically. If you use a direct
                download, first compare it with the release{' '}
                <a href={manifest.checksum_url}>SHA256SUMS.txt</a>; the browser download button does
                not perform that check for you.
              </p>
            ) : null}

            <p>
              A macOS app copied from a DMG in Finder has no FlintTrade install receipt. To remove
              that manual copy, quit FlintTrade and move <span className="font-mono">FlintTrade.app</span>{' '}
              to Trash; application data stays available for reinstall. The ordinary uninstall script
              removes only receipt-proved shells installed by the one-command path.
            </p>

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

            {installScriptSourceUrl ? (
              <>
                <h2>One-command install</h2>
                <p>
                  These commands download, verify, and install the matching shell asset. The source build
                  begins inside the app on first launch, where progress, retry, and recovery stay visible.
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
              </>
            ) : (
              <p>
                One-command install is unavailable because this site deployment has no immutable
                source identity. Use a direct download and verify it against SHA256SUMS.txt.
              </p>
            )}

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

            <h2>What happens on first launch</h2>
            <p>
              The shell verifies its pinned tool distributions, acquires the FlintTrade checkout,
              syncs frozen Python and JavaScript dependencies, and builds the terminal. The
              hash-verified, integrity-locked local source is built before the main window opens;
              that window also waits for backend health proof.
            </p>
          </>
        ) : (
          <section aria-labelledby="electron-installer-pending">
            <h2 id="electron-installer-pending">Electron installer release pending</h2>
            <p>
              No complete, checksum-published Electron installer release is available yet. Existing
              GitHub releases may use the previous desktop packaging, so this page does not expose
              download buttons or one-command install instructions until the full Electron asset set
              is published and verified.
            </p>
            <p>
              Follow the{' '}
              <a href="https://github.com/navaneeshnagarajan/FlintTrade/releases" target="_blank" rel="noopener noreferrer">
                GitHub release history
              </a>{' '}
              or return here after the Electron release is published.
            </p>
          </section>
        )}

        <div className="section-actions">
          <Link className="button primary" href="/docs/desktop">
            Desktop guide <ArrowRight aria-hidden="true" size={17} />
          </Link>
          {installerReleaseAvailable && (
            <>
              <a className="button secondary" href="/api/desktop-release">
                Release metadata <Terminal aria-hidden="true" size={17} />
              </a>
              {installScriptSourceUrl ? (
                <a
                  className="button secondary"
                  href={installScriptSourceUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Read the install script <ExternalLink aria-hidden="true" size={17} />
                </a>
              ) : null}
            </>
          )}
        </div>

        <p className="hero-disclaimer">
          {installerReleaseAvailable
            ? `${manifest.tag} is not production ready.`
            : 'FlintTrade remains beta software and no Electron installer is currently offered.'}{' '}
          Use Explore and Practice modes first; Live mode remains your own risk.
        </p>
      </section>
      <SiteFooter />
    </main>
  );
}
