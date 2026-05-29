import Link from 'next/link';

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <p>FlintTrade is AGPL-3.0 open source software built for self-hosted Indian market workflows.</p>
      <div>
        <Link href="/docs">Docs</Link>
        <Link href="/mcp">MCP</Link>
        <Link href="/contribute">Contribute</Link>
        <a href="/llms.txt">llms.txt</a>
      </div>
    </footer>
  );
}
