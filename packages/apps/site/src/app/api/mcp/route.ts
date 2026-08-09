import { createFlintDocsMcpHttpHandler } from '@/lib/mcp/registry';
import { APP_VERSION } from '@/lib/version';

/**
 * Stateless dual-era docs MCP HTTP surface.
 * Callable handler (not `.fetch`); each request gets a fresh registration
 * via mcp-handler@2.1 + @modelcontextprotocol/server@2.0.0.
 */
const handler = createFlintDocsMcpHttpHandler({
  name: 'flinttrade-docs',
  version: APP_VERSION,
});

/**
 * Next.js route wrappers (explicit `Request` first arg) delegating to the
 * fetch-compatible callable handler. Keeps maxDuration=30 and the internal
 * handler available for tests.
 */
export async function GET(request: Request): Promise<Response> {
  return handler(request);
}

export async function POST(request: Request): Promise<Response> {
  return handler(request);
}

export async function DELETE(request: Request): Promise<Response> {
  return handler(request);
}

export const maxDuration = 30;
