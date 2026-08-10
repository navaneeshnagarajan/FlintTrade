import { serveStdio } from '@modelcontextprotocol/server/stdio';

import { createFlintDocsMcpServer } from '../lib/mcp/registry';
import { APP_VERSION } from '../lib/version';

/**
 * Local stdio docs MCP entrypoint.
 * Fresh server factory per session; same public catalogue as HTTP.
 * Dual-era: legacy openings are served (`legacy: 'serve'`); factory errors surface via onerror.
 * Cache: SDK-v2 fixed defaults (ttlMs=0, cacheScope=private) — no cacheHints config.
 */
const handle = serveStdio(
  () =>
    createFlintDocsMcpServer({
      name: 'flinttrade-docs-local',
      version: APP_VERSION,
    }),
  {
    // Keep 2025 clients usable on the same entrypoint as 2026 modern clients.
    legacy: 'serve',
    onerror: (error) => {
      // Reporting only — must not swallow. Surface on stderr for spawn diagnostics.
      const message = error instanceof Error ? error.stack ?? error.message : String(error);
      process.stderr.write(`[flinttrade-docs-local] ${message}\n`);
    },
  },
);

void handle;
