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
            <pre>{`make setup
make test-fast
make lint
cd packages/apps/terminal && npm run typecheck
cd packages/apps/site && npm run build`}</pre>
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
