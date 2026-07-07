import { ArrowRight, ExternalLink, GitBranch, Hammer, RefreshCw, ShieldCheck } from 'lucide-react';
import Link from 'next/link';

import { SiteFooter } from '@/components/site-footer';
import { SiteHeader } from '@/components/site-header';

export const metadata = {
  title: 'Download',
  description:
    'Install FlintTrade with one command — the bootstrap installer fetches the latest release from GitHub and builds the desktop app on your own machine.',
};

const guarantees = [
  {
    icon: GitBranch,
    title: 'Always the latest release',
    copy: 'The installer resolves the newest release tag from GitHub at run time, so the same command installs today and updates tomorrow.',
  },
  {
    icon: Hammer,
    title: 'Built on your machine',
    copy: 'Nothing pre-built to trust: the script clones the tagged source and compiles the backend sidecar and native shell locally. No unsigned-binary warnings.',
  },
  {
    icon: RefreshCw,
    title: 'Updating is the same command',
    copy: 'Re-run the one-liner (or use the in-app updater) and it fetches the newest tag into the same source workspace and rebuilds.',
  },
  {
    icon: ShieldCheck,
    title: 'No silent system changes',
    copy: 'The script never elevates or installs system packages silently — it prints the exact command for anything missing and stops.',
  },
];

const platforms = [
  {
    platform: 'macOS (Apple Silicon & Intel)',
    command: 'curl -fsSL https://flinttrade.vercel.app/install.sh | bash',
    needs: 'Xcode Command Line Tools, Rust, Node 22+, uv (the script offers to install uv and pnpm itself).',
  },
  {
    platform: 'Linux (x64 & arm64)',
    command: 'curl -fsSL https://flinttrade.vercel.app/install.sh | bash',
    needs: 'Rust, Node 22+, uv, and the Tauri system libraries (webkit2gtk — the script prints your distro’s exact install command).',
  },
  {
    platform: 'Windows 10/11 (x64)',
    command: 'irm https://flinttrade.vercel.app/install.ps1 | iex',
    needs: 'Git for Windows, Rust (MSVC toolchain + VS Build Tools), Node 22+, uv.',
  },
];

export default function DownloadPage() {
  return (
    <main className="site-shell">
      <SiteHeader />
      <section className="subpage">
        <h1>One command. Built from source, on your machine.</h1>
        <p>
          The FlintTrade installer fetches the latest release tag from GitHub and builds the
          native desktop app locally — the same way tools like rustup and Homebrew bootstrap
          themselves. The first build takes roughly 10–20 minutes and needs a working developer
          toolchain plus a few GB of disk; every later update reuses the same workspace and is
          much faster. Prefer a pre-built installer? Those live on{' '}
          <a
            href="https://github.com/navaneeshnagarajan/FlintTrade/releases"
            target="_blank"
            rel="noopener noreferrer"
          >
            GitHub releases
          </a>
          .
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

        <div className="section-actions">
          <Link className="button primary" href="/docs/desktop">
            Desktop guide (what the app bundles) <ArrowRight aria-hidden="true" size={17} />
          </Link>
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
          v0.6.0-beta.1 is not production ready. Use Explore and Practice modes first; Live mode
          remains your own risk.
        </p>
      </section>
      <SiteFooter />
    </main>
  );
}
