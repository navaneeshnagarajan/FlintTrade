import { createMcpHandler } from 'mcp-handler';

import { registerFlintDocsMcp } from '@/lib/mcp/registry';
import { APP_VERSION } from '@/lib/version';

const handler = createMcpHandler(
  (server) => {
    registerFlintDocsMcp(server);
  },
  {
    serverInfo: {
      name: 'flinttrade-docs',
      version: APP_VERSION,
    },
  },
  {
    basePath: '/api',
    disableSse: true,
    maxDuration: 30,
  },
);

export { handler as DELETE, handler as GET, handler as POST };
