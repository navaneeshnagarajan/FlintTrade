import Link from 'next/link';

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <p>FlintTrade is AGPL-3.0 open source software built for self-hosted Indian market workflows.</p>
      <nav aria-label="Footer navigation">
        <Link href="/explore">Explore</Link>
        <Link href="/download">Install the web app</Link>
        <Link href="/docs/disclaimer">Risk disclaimer</Link>
        <Link href="/docs/desktop">Desktop App</Link>
        <Link href="/docs">Docs</Link>
        <Link href="/api-reference">API reference</Link>
        <Link href="/mcp">MCP</Link>
        <Link href="/contribute">Contribute</Link>
        <a href="/llms.txt">llms.txt</a>
        <a href="/llms-full.txt">Full documentation text</a>
      </nav>
    </footer>
  );
}
