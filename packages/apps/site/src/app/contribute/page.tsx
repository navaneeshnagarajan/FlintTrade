import { ArrowRight, CheckCircle2, GitPullRequest, TestTube2 } from 'lucide-react';
import Link from 'next/link';

import { SiteFooter } from '@/components/site-footer';
import { SiteHeader } from '@/components/site-header';

const steps = [
  {
    icon: CheckCircle2,
    title: 'Start from the canonical docs',
    copy: 'Read the Developer Guide, Architecture, API reference, and affected package README before editing.',
  },
  {
    icon: TestTube2,
    title: 'Run focused checks first',
    copy: 'Use package-specific pytest, terminal Vitest/typecheck, or the site build before broader Makefile checks.',
  },
  {
    icon: GitPullRequest,
    title: 'Open a small PR',
    copy: 'Use Conventional Commits, list tests run, update docs when behaviour changes, and include screenshots for UI work.',
  },
];

export const metadata = {
  title: 'Contribute',
  description: 'Contributor onboarding for the FlintTrade monorepo.',
};

export default function ContributePage() {
  return (
    <main className="site-shell">
      <SiteHeader />
      <section className="subpage">
        <h1>Contribute without getting lost.</h1>
        <p>
          FlintTrade spans Python services, a React terminal, Rust tick processing,
          native broker integrations, and a desktop shell. The public docs and MCP tools are designed
          to get contributors to the right package, tests, and context quickly.
        </p>

        <div className="feature-grid">
          {steps.map((step) => {
            const Icon = step.icon;
            return (
              <article className="feature-card" key={step.title}>
                <Icon aria-hidden="true" />
                <h3>{step.title}</h3>
                <p>{step.copy}</p>
              </article>
            );
          })}
        </div>

        <div className="stack">
          <div className="code-panel">
            <header>
              <span>Useful first commands</span>
              <span>repo root</span>
            </header>
            <pre>{`python scripts/ft.py setup
python scripts/ft.py test
python scripts/ft.py lint`}</pre>
            <p className="code-panel-note">
              The cross-platform runner needs no make and no bash, so these lines behave identically
              in Windows PowerShell, bash and zsh. On POSIX,{' '}
              <span className="font-mono">make setup</span>, <span className="font-mono">make test</span>{' '}
              and <span className="font-mono">make lint</span> are the aliases;{' '}
              <span className="font-mono">make test-fast</span> stops at the first failure.
            </p>
          </div>
          <div className="code-panel">
            <header>
              <span>Package checks</span>
              <span>one command per line</span>
            </header>
            <pre>{`cd packages/apps/terminal
npm run typecheck

cd packages/apps/site
npm run build`}</pre>
            <p className="code-panel-note">
              Windows PowerShell has no <span className="font-mono">{'&&'}</span> chaining, so the
              directory change and the command it feeds are listed separately rather than joined.
            </p>
          </div>
        </div>

        <div className="hero-actions">
          <Link className="button primary" href="/docs/developer-guide">
            Developer guide <ArrowRight aria-hidden="true" size={17} />
          </Link>
          <Link className="button secondary" href="/mcp">
            Configure MCP
          </Link>
        </div>
      </section>
      <SiteFooter />
    </main>
  );
}
