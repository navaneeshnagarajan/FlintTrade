import { LogoIcon } from '@flinttrade/design-system/brand';
import Link from 'next/link';

import { GithubIcon } from '@/components/github-icon';
import { ThemeToggle } from '@/components/theme-toggle';

const navItems = [
  { href: '/explore', label: 'Explore' },
  { href: '/download', label: 'Download' },
  { href: '/demo-app/welcome', label: 'Demo (example data)', newWindow: true },
  { href: '/docs', label: 'Docs' },
  { href: '/api-reference', label: 'API' },
  { href: '/mcp', label: 'MCP' },
  { href: '/contribute', label: 'Contribute' },
];

function NavigationLinks({ activePath }: { activePath?: string }) {
  return navItems.map((item) => (
    <Link
      key={item.href}
      href={item.href}
      aria-current={activePath === item.href ? 'page' : undefined}
      target={item.newWindow ? '_blank' : undefined}
      rel={item.newWindow ? 'noopener noreferrer' : undefined}
    >
      {item.label}
    </Link>
  ));
}

export function SiteHeader({ activePath }: { activePath?: string }) {
  return (
    <header className="site-header">
      <a className="site-skip-link" href="#site-content">Skip to content</a>
      <Link href="/" className="brand-link" aria-label="FlintTrade home">
        <LogoIcon size={24} aria-hidden="true" />
        <span>FlintTrade</span>
      </Link>
      <nav className="main-nav" aria-label="Primary navigation">
        <NavigationLinks activePath={activePath} />
      </nav>
      <div className="header-tools">
        <ThemeToggle />
        <Link
          className="github-link"
          href="https://github.com/navaneeshnagarajan/FlintTrade"
          target="_blank"
          rel="noreferrer"
          aria-label="Open FlintTrade on GitHub"
        >
          <GithubIcon aria-hidden="true" />
        </Link>
      </div>
      <details className="site-menu">
        <summary>Menu</summary>
        <nav aria-label="Compact navigation">
          <NavigationLinks activePath={activePath} />
        </nav>
      </details>
    </header>
  );
}
