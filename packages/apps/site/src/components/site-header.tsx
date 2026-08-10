import { LogoIcon } from '@flinttrade/design-system/brand';
import Link from 'next/link';

import { GithubIcon } from '@/components/github-icon';
import { ThemeToggle } from '@/components/theme-toggle';

const navItems = [
  { href: '/download', label: 'Download' },
  { href: '/demo-app/welcome', label: 'Explore demo', newWindow: true },
  { href: '/docs', label: 'Docs' },
  { href: '/api-reference', label: 'API' },
  { href: '/mcp', label: 'MCP' },
  { href: '/contribute', label: 'Contribute' },
];

export function SiteHeader() {
  return (
    <header className="site-header">
      <Link href="/" className="brand-link" aria-label="FlintTrade home">
        <LogoIcon size={24} aria-hidden="true" />
        <span>FlintTrade</span>
      </Link>
      <nav className="main-nav" aria-label="Primary navigation">
        {navItems.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            target={item.newWindow ? '_blank' : undefined}
            rel={item.newWindow ? 'noopener noreferrer' : undefined}
          >
            {item.label}
          </Link>
        ))}
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
    </header>
  );
}
