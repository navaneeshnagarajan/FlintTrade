import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';

import { registerFlintDocsMcp } from '../lib/mcp/registry';
import { APP_VERSION } from '../lib/version';

async function main(): Promise<void> {
  const server = new McpServer({
    name: 'flinttrade-docs-local',
    version: APP_VERSION,
  });

  registerFlintDocsMcp(server);
  await server.connect(new StdioServerTransport());
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
