import { Cable, LockKeyhole, Search, TerminalSquare } from 'lucide-react';
import Link from 'next/link';

import { SiteFooter } from '@/components/site-footer';
import { SiteHeader } from '@/components/site-header';
import { DOCS_MCP_PROMPT_NAMES, DOCS_MCP_TOOL_NAMES } from '@/lib/mcp/capabilities';

const resources = [
  'flinttrade://docs/index',
  'flinttrade://docs/{slug}',
  'flinttrade://packages',
  'flinttrade://packages/{name}',
  'flinttrade://contributing',
  'flinttrade://commands',
];

export const metadata = {
  title: 'Docs MCP',
  description: 'Read-only MCP server for FlintTrade docs, package orientation, and contribution workflows.',
};

export default function McpPage() {
  return (
    <main className="site-shell">
      <SiteHeader />
      <section className="subpage">
        <h1>Docs MCP for FlintTrade contributors.</h1>
        <p>
          Use the hosted endpoint for public docs assistants or the local stdio command inside a cloned repo.
          This MCP surface is read-only and intentionally separate from FlintTrade broker-workflow automation.
        </p>

        <div className="feature-grid">
          <article className="feature-card">
            <Search aria-hidden="true" />
            <h3>Search and read docs</h3>
            <p>Query root docs, setup guides, release notes, and package README content from one generated index.</p>
          </article>
          <article className="feature-card">
            <TerminalSquare aria-hidden="true" />
            <h3>Plan contribution work</h3>
            <p>Ask for path explanations, package maps, test recommendations, and change planning prompts.</p>
          </article>
          <article className="feature-card">
            <LockKeyhole aria-hidden="true" />
            <h3>No order powers</h3>
            <p>Broker auth, account state, funds, order IDs, and order placement are not registered here.</p>
          </article>
        </div>

        <div className="stack">
          <div className="code-panel">
            <header>
              <span>Hosted Streamable HTTP</span>
              <span>/api/mcp</span>
            </header>
            <pre>{`{
  "mcpServers": {
    "flinttrade-docs": {
      "url": "https://<your-flinttrade-site>/api/mcp"
    }
  }
}`}</pre>
          </div>

          <div className="code-panel">
            <header>
              <span>Local stdio</span>
              <span>repo-aware</span>
            </header>
            <pre>{`{
  "mcpServers": {
    "flinttrade-local": {
      "command": "npm",
      "args": ["run", "mcp:stdio"],
      "cwd": "/path/to/FlintTrade/packages/apps/site"
    }
  }
}`}</pre>
          </div>
        </div>

        <section className="section-heading">
          <h2>Registered tools</h2>
          <p>{DOCS_MCP_TOOL_NAMES.join(', ')}</p>
        </section>

        <section className="section-heading">
          <h2>Resources</h2>
          <p>{resources.join(', ')}</p>
        </section>

        <section className="section-heading">
          <h2>Prompts</h2>
          <p>{DOCS_MCP_PROMPT_NAMES.join(', ')}</p>
        </section>

        <Link className="button primary" href="/docs/mcp">
          Read generated MCP docs <Cable aria-hidden="true" size={17} />
        </Link>
      </section>
      <SiteFooter />
    </main>
  );
}
