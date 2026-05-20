import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';

import { registerFlintDocsMcp } from '../lib/mcp/registry';

async function main(): Promise<void> {
  const server = new McpServer({
    name: 'flinttrade-docs-local',
    version: '0.1.0',
  });

  registerFlintDocsMcp(server);
  await server.connect(new StdioServerTransport());
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
