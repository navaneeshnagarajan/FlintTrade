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
    'Install the self-hosted FlintTrade web app in one line, and check Electron installer availability for macOS, Windows, and Linux.',
};

// The self-hosted web app is the primary path: it needs nothing pre-installed
// and, unlike the desktop shell, it does not wait on a published release. These
// commands are the canonical one-liners and must stay byte-for-byte identical
// to the ones in the setup docs and the repository readme.
const webInstallCommands = [
  {
    platform: 'macOS / Linux',
    command: 'curl -fsSL https://flinttrade.vercel.app/web-install.sh | bash',
    needs: 'No prerequisites. Provisions a pinned, checksum-verified toolchain, builds the managed source checkout, and installs the flinttrade launcher.',
  },
  {
    platform: 'Windows 10/11',
    command: 'irm https://flinttrade.vercel.app/web-install.ps1 | iex',
    needs: 'No prerequisites. Same bootstrap in PowerShell, with a per-user launcher and a Start Menu shortcut.',
  },
] as const;

// The hosted one-liners are a redirect to these same scripts, so every route on
// this site answers 503 when a deployment has no immutable source commit. These
// repo-direct commands depend on no deployment at all and must stay visible in
// every state — a reader who hits the 503 is exactly the reader who needs them.
const repoDirectCommands = [
  {
    platform: 'macOS / Linux',
    command:
      'curl -fsSL https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade/main/scripts/install/flinttrade-web-install.sh | bash',
    needs: 'Same script, fetched from the repository instead of this site. Swap flinttrade-web-install for flinttrade-uninstall to remove FlintTrade.',
  },
  {
    platform: 'Windows 10/11',
    command:
      'irm https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade/main/scripts/install/flinttrade-web-install.ps1 | iex',
    needs: 'Same script in PowerShell. Swap flinttrade-web-install for flinttrade-uninstall to remove FlintTrade.',
  },
] as const;

const uninstallCommands = [
  {
    platform: 'macOS / Linux',
    command: 'curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash',
    purgeLabel: '# add --purge to also delete the workspace and its data',
    purge: 'curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash -s -- --purge',
    needs: 'Removes the app, launcher, and managed tools. Your workspace and its data are kept unless you add --purge.',
  },
  {
    platform: 'Windows 10/11',
    command: 'irm https://flinttrade.vercel.app/uninstall.ps1 | iex',
    purgeLabel: '# add -Purge to also delete the workspace and its data',
    purge: '& ([scriptblock]::Create((irm https://flinttrade.vercel.app/uninstall.ps1))) -Purge',
    needs: 'Removes the app, launcher, and managed tools. Your workspace and its data are kept unless you add -Purge.',
  },
] as const;

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

/**
 * Outcome of the release lookup. `lookupFailed` separates "we could not ask
 * GitHub" from "GitHub answered and there is no complete release yet" — the
 * two used to collapse into the same pending copy, which told a visitor that
 * nothing was published when in fact we simply had not looked successfully.
 */
interface DesktopReleaseLookup {
  manifest: DesktopReleaseManifest;
  lookupFailed: boolean;
}

async function releaseForDownloadPage(): Promise<DesktopReleaseLookup> {
  try {
    const response = await fetch(GITHUB_RELEASES_URL, {
      headers: {
        Accept: 'application/vnd.github+json',
        'User-Agent': 'flinttrade-site/download-page',
      },
      next: { revalidate: 300 },
    });
    if (!response.ok) return { manifest: DEFAULT_DESKTOP_RELEASE, lookupFailed: true };
    const releases = (await response.json()) as GitHubRelease[];
    return {
      manifest: selectDesktopRelease(releases, { channel: 'beta' }) ?? DEFAULT_DESKTOP_RELEASE,
      lookupFailed: false,
    };
  } catch {
    return { manifest: DEFAULT_DESKTOP_RELEASE, lookupFailed: true };
  }
}

/**
 * Shown whenever the desktop shell cannot be offered. A failed lookup and an
 * unpublished release are different facts, so they get different copy — and
 * neither of them withholds the web app, which is installable in every state.
 */
function DesktopShellUnavailable({ lookupFailed }: { lookupFailed: boolean }) {
  if (lookupFailed) {
    return (
      <section aria-labelledby="electron-release-lookup-failed">
        <h2 id="electron-release-lookup-failed">Desktop release status temporarily unavailable</h2>
        <p>
          The GitHub release feed could not be reached from this deployment, so desktop installer
          availability could not be checked just now. This is a temporary lookup failure, not a
          statement that an installer does or does not exist. Reload shortly, or read the{' '}
          <a href="https://github.com/navaneeshnagarajan/FlintTrade/releases" target="_blank" rel="noopener noreferrer">
            GitHub release history
          </a>{' '}
          directly. The web app above is unaffected.
        </p>
      </section>
    );
  }
  return (
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
        or return here after the Electron release is published. Until then, the self-hosted web
        app above is the supported way to run FlintTrade.
      </p>
    </section>
  );
}

/** Closing disclaimer lead-in; it must never claim a fact the lookup did not establish. */
function desktopAvailabilityNote(
  manifest: DesktopReleaseManifest,
  installerReleaseAvailable: boolean,
  lookupFailed: boolean,
): string {
  if (installerReleaseAvailable) return `${manifest.tag} is not production ready.`;
  if (lookupFailed) {
    return 'FlintTrade remains beta software and desktop installer availability could not be checked.';
  }
  return 'FlintTrade remains beta software and no Electron installer is currently offered.';
}

export default async function DownloadPage() {
  const { manifest, lookupFailed } = await releaseForDownloadPage();
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
        <h1>Install FlintTrade.</h1>

        <section aria-labelledby="web-app-install">
          <h2 id="web-app-install">Install the self-hosted web app</h2>
          <p>
            This is the primary path and it needs nothing pre-installed — no Python, no Node, no
            git, no bash and no make. The installer provisions a pinned, checksum-verified
            toolchain, builds FlintTrade from a managed source checkout, and installs a{' '}
            <span className="font-mono">flinttrade</span> launcher. Open{' '}
            <span className="font-mono">http://127.0.0.1:5100</span> and complete Setup; no{' '}
            <span className="font-mono">.env</span> file is required.
          </p>
          <div className="stack">
            {webInstallCommands.map((entry) => (
              <div className="code-panel" key={entry.platform}>
                <header>
                  <span>{entry.platform}</span>
                  <span>terminal</span>
                </header>
                <pre>
                  <code>{entry.command}</code>
                </pre>
                <p className="code-panel-note">{entry.needs}</p>
              </div>
            ))}
          </div>
          {sourceSha === null ? (
            <p>
              This site deployment has no immutable source identity, so those bootstrap URLs answer
              503 rather than redirect. Clone the repository and run{' '}
              <span className="font-mono">scripts/install/flinttrade-web-install.sh</span> (or{' '}
              <span className="font-mono">flinttrade-web-install.ps1</span>) directly until the site
              is redeployed from a known commit.
            </p>
          ) : null}
        </section>

        <section aria-labelledby="uninstall-flinttrade">
          <h2 id="uninstall-flinttrade">Uninstall</h2>
          <p>
            The same one-line shape removes FlintTrade. Your workspace and its data survive by
            default; the purge form deletes them too, and that deletion cannot be undone.
          </p>
          <div className="stack">
            {uninstallCommands.map((entry) => (
              <div className="code-panel" key={entry.platform}>
                <header>
                  <span>{entry.platform}</span>
                  <span>terminal</span>
                </header>
                <pre>
                  <code>{`# ordinary uninstall\n${entry.command}\n${entry.purgeLabel}\n${entry.purge}`}</code>
                </pre>
                <p className="code-panel-note">{entry.needs}</p>
              </div>
            ))}
          </div>
          {sourceSha === null ? (
            <p>
              This site deployment has no immutable source identity, so those uninstall URLs
              answer 503 rather than redirect. Clone the repository and run{' '}
              <span className="font-mono">scripts/install/flinttrade-uninstall.sh</span> (or{' '}
              <span className="font-mono">flinttrade-uninstall.ps1</span>) directly until the
              site is redeployed from a known commit.
            </p>
          ) : null}
        </section>

        <section aria-labelledby="repo-direct-fallback">
          <h2 id="repo-direct-fallback">If this site is unreachable</h2>
          <p>
            Use these whenever a command above fails: every install and uninstall URL here is
            only a redirect to a script in the repository, so an outage — or a deployment
            without an immutable source commit — answers 503, and piping that response into a
            shell does nothing useful. The commands below fetch the same scripts from the
            repository and depend on no deployment.
          </p>
          <div className="stack">
            {repoDirectCommands.map((entry) => (
              <div className="code-panel" key={entry.platform}>
                <header>
                  <span>{entry.platform}</span>
                  <span>terminal</span>
                </header>
                <pre>
                  <code>{entry.command}</code>
                </pre>
                <p className="code-panel-note">{entry.needs}</p>
              </div>
            ))}
          </div>
          <p>
            These follow the repository default branch rather than a pinned commit, so read the
            script first if that is your policy. To do that, clone the repository and run{' '}
            <span className="font-mono">scripts/install/flinttrade-web-install.sh</span> (or{' '}
            <span className="font-mono">flinttrade-web-install.ps1</span>) from the checkout.
            The desktop shell installer and uninstaller live beside them in{' '}
            <span className="font-mono">scripts/install/</span> and run the same way.
          </p>
        </section>

        {installerReleaseAvailable ? (
          <>
            <h2>FlintTrade Desktop</h2>
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
          <DesktopShellUnavailable lookupFailed={lookupFailed} />
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
          {desktopAvailabilityNote(manifest, installerReleaseAvailable, lookupFailed)}{' '}
          Use Explore and Practice modes first; Live mode remains your own risk.
        </p>
      </section>
      <SiteFooter />
    </main>
  );
}
