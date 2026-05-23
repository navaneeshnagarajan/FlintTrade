import { Github } from 'lucide-react';
import Image from 'next/image';
import Link from 'next/link';

const navItems = [
  { href: '/docs', label: 'Docs' },
  { href: '/api-reference', label: 'API' },
  { href: '/mcp', label: 'MCP' },
  { href: '/contribute', label: 'Contribute' },
];

export function SiteHeader() {
  return (
    <header className="site-header">
      <Link href="/" className="brand-link" aria-label="FlintTrade home">
        <Image src="/flinttrade/logo.svg" alt="" width={34} height={34} />
        <span>FlintTrade</span>
      </Link>
      <nav className="main-nav" aria-label="Primary navigation">
        {navItems.map((item) => (
          <Link key={item.href} href={item.href}>
            {item.label}
          </Link>
        ))}
      </nav>
      <Link
        className="github-link"
        href="https://github.com/navaneeshnagarajan/FlintTrade"
        target="_blank"
        rel="noreferrer"
        aria-label="Open FlintTrade on GitHub"
      >
        <Github aria-hidden="true" />
      </Link>
    </header>
  );
}
