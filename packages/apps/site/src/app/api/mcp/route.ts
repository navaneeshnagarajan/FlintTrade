import { createMcpHandler } from 'mcp-handler';

import { registerFlintDocsMcp } from '@/lib/mcp/registry';

const handler = createMcpHandler(
  (server) => {
    registerFlintDocsMcp(server);
  },
  {
    serverInfo: {
      name: 'flinttrade-docs',
      version: '0.1.0',
    },
  },
  {
    basePath: '/api',
    disableSse: true,
    maxDuration: 30,
  },
);

export { handler as DELETE, handler as GET, handler as POST };
