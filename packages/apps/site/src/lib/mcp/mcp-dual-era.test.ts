import { describe, expect, it } from 'vitest';
import { Client, StreamableHTTPClientTransport } from '@modelcontextprotocol/client';
import { StdioClientTransport } from '@modelcontextprotocol/client/stdio';
import { GET as routeGet } from '../../app/api/mcp/route';
import { APP_VERSION } from '../version';
import {
  assertDocsMcpSafety,
  DOCS_MCP_PROMPT_NAMES,
  DOCS_MCP_TOOL_NAMES,
} from './capabilities';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { existsSync, readFileSync } from 'node:fs';

// MCP 2026 dual-era docs-server pilot — real executable matrix (no placeholders).
// Pin: { versionNegotiation: { mode: { pin: '2026-07-28' } } }
// Callable handler (fetch-compatible, not `.fetch`); real stdio/cache/safety;
// modern success expectations; no explicit any; spawn/connect errors propagate.

const EXPECTED_TOOL_NAMES = [
  'search_docs',
  'get_doc',
  'list_packages',
  'explain_repo_path',
  'recommend_tests',
  'make_contribution_plan',
] as const;

const EXPECTED_PROMPT_NAMES = [
  'plan_contribution',
  'add_terminal_widget',
  'add_python_feature',
  'update_docs_for_change',
] as const;

const EXPECTED_STATIC_RESOURCES = [
  'flinttrade://docs/index',
  'flinttrade://packages',
  'flinttrade://contributing',
  'flinttrade://commands',
] as const;

const EXPECTED_RESOURCE_TEMPLATES = [
  'flinttrade://docs/{slug}',
  'flinttrade://packages/{name}',
] as const;

/** Site package root so stdio spawn resolves `src/mcp/stdio.ts` regardless of vitest cwd. */
const SITE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const REPO_ROOT = path.resolve(SITE_ROOT, '../../..');

type CacheableResult = {
  ttlMs: number;
  cacheScope: string;
};

type TextContentItem = {
  type?: string;
  text?: string;
};

type FlintDocsMcpHttpHandler = {
  (input: Request): Promise<Response>;
  (input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
};

function createTestHandler(): FlintDocsMcpHttpHandler {
  const invokeRoute = routeGet as unknown as (request: Request) => Promise<Response>;
  return (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const request = input instanceof Request ? input : new Request(input, init);
    return invokeRoute(request);
  };
}

function asFetch(handler: FlintDocsMcpHttpHandler): typeof fetch {
  return handler as unknown as typeof fetch;
}

function createStdioTransport(): StdioClientTransport {
  // Real spawn of the stdio entrypoint (fresh factory per session) using repo-local tsx.
  // Failures must reject connect — no try/catch swallow. No npx network.
  const tsxBin = process.platform === 'win32'
    ? path.join(SITE_ROOT, 'node_modules/.bin/tsx.cmd')
    : path.join(SITE_ROOT, 'node_modules/.bin/tsx');
  return new StdioClientTransport({
    command: tsxBin,
    args: ['src/mcp/stdio.ts'],
    cwd: SITE_ROOT,
    stderr: 'pipe',
  });
}

function clientEra(client: Client): string {
  const withEra = client as Client & { getProtocolEra?: () => string | undefined };
  if (typeof withEra.getProtocolEra === 'function') {
    return withEra.getProtocolEra() ?? 'unknown';
  }
  return 'unknown';
}

function assertToolTextResult(result: { content?: TextContentItem[] | null }): void {
  expect(Array.isArray(result.content)).toBe(true);
  expect(result.content!.length).toBeGreaterThan(0);
  const first = result.content![0];
  expect(first.type).toBe('text');
  expect(typeof first.text).toBe('string');
  expect((first.text ?? '').length).toBeGreaterThan(0);
}

/** Parse JSON body or first SSE `data:` payload from an MCP HTTP response. */
async function readJsonRpcBody(res: Response): Promise<Record<string, unknown>> {
  const text = await res.text();
  const trimmed = text.trim();
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    return JSON.parse(trimmed) as Record<string, unknown>;
  }
  const dataLine = trimmed
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find((line) => line.startsWith('data:'));
  if (!dataLine) {
    throw new Error(`Expected JSON or SSE data payload, got: ${trimmed.slice(0, 200)}`);
  }
  return JSON.parse(dataLine.slice('data:'.length).trim()) as Record<string, unknown>;
}

async function assertExactPublicCatalogue(client: Client): Promise<void> {
  const tools = await client.listTools();
  expect(tools.tools.map((t) => t.name)).toEqual([...EXPECTED_TOOL_NAMES]);

  const resources = await client.listResources();
  const uris = resources.resources.map((r) => r.uri);
  expect(resources.resources.length).toBeGreaterThanOrEqual(EXPECTED_STATIC_RESOURCES.length);
  for (const staticUri of EXPECTED_STATIC_RESOURCES) {
    expect(uris).toContain(staticUri);
  }

  const templates = await client.listResourceTemplates();
  expect(templates.resourceTemplates.map((t) => t.uriTemplate)).toEqual([
    ...EXPECTED_RESOURCE_TEMPLATES,
  ]);

  const prompts = await client.listPrompts();
  expect(prompts.prompts.map((p) => p.name)).toEqual([...EXPECTED_PROMPT_NAMES]);
}

async function assertListedSlashNamedPackageIsReadable(client: Client): Promise<void> {
  const resources = await client.listResources();
  const packageResource = resources.resources.find((resource) => resource.name === 'apps/site');
  expect(packageResource).toBeDefined();
  if (!packageResource) throw new Error('The apps/site package resource was not listed.');

  expect(packageResource.uri).toBe('flinttrade://packages/apps%2Fsite');
  const read = await client.readResource({ uri: packageResource.uri });
  expect(read.contents.length).toBeGreaterThan(0);
  const firstContent = read.contents[0] as { text?: string };
  expect(firstContent.text).toContain('Source: packages/apps/site/README.md');
}

describe('MCP 2026 dual-era protocol matrix (target-state RED/GREEN)', () => {
  it('1. Modern HTTP: versionNegotiation pinned 2026-07-28 connects as era=modern, lists exact tools/resources/prompts, and calls one read-only tool', async () => {
    const fetchFn = createTestHandler();
    const client = new Client(
      { name: 'red-test-client', version: '1.0.0' },
      { versionNegotiation: { mode: { pin: '2026-07-28' } } },
    );
    const transport = new StreamableHTTPClientTransport(new URL('http://test.local/api/mcp'), {
      fetch: asFetch(fetchFn),
    });

    await client.connect(transport);
    expect(clientEra(client)).toBe('modern');

    await assertExactPublicCatalogue(client);
    await assertListedSlashNamedPackageIsReadable(client);

    const result = await client.callTool({ name: 'search_docs', arguments: { query: 'gateway' } });
    assertToolTextResult(result);

    await client.close();
  });

  it('2. Auto HTTP: versionNegotiation:auto selects modern against the migrated HTTP server', async () => {
    const fetchFn = createTestHandler();
    const client = new Client(
      { name: 'red-test-client', version: '1.0.0' },
      { versionNegotiation: { mode: 'auto' } },
    );
    const transport = new StreamableHTTPClientTransport(new URL('http://test.local/api/mcp'), {
      fetch: asFetch(fetchFn),
    });

    await client.connect(transport);
    expect(clientEra(client)).toBe('modern');
    await client.close();
  });

  it('3. Legacy HTTP: default/legacy negotiation still initialises as 2025-11-25, lists the same public catalogue, and calls one read-only tool', async () => {
    const fetchFn = createTestHandler();
    const client = new Client({ name: 'red-test-client', version: '1.0.0' });
    const transport = new StreamableHTTPClientTransport(new URL('http://test.local/api/mcp'), {
      fetch: asFetch(fetchFn),
    });

    await client.connect(transport);
    expect(clientEra(client)).toBe('legacy');

    await assertExactPublicCatalogue(client);

    const result = await client.callTool({ name: 'list_packages', arguments: {} });
    assertToolTextResult(result);

    await client.close();
  });

  it('4. Modern stdio: pinned 2026 connects as modern and lists/calls the same catalogue', async () => {
    const client = new Client(
      { name: 'red-test-client', version: '1.0.0' },
      { versionNegotiation: { mode: { pin: '2026-07-28' } } },
    );
    const transport = createStdioTransport();
    await client.connect(transport);
    expect(clientEra(client)).toBe('modern');

    const tools = await client.listTools();
    expect(tools.tools.map((t) => t.name)).toEqual([...EXPECTED_TOOL_NAMES]);

    const result = await client.callTool({ name: 'list_packages', arguments: {} });
    assertToolTextResult(result);

    await client.close();
  });

  it('5. Auto stdio: auto selects modern', async () => {
    const client = new Client(
      { name: 'red-test-client', version: '1.0.0' },
      { versionNegotiation: { mode: 'auto' } },
    );
    const transport = createStdioTransport();
    await client.connect(transport);
    expect(clientEra(client)).toBe('modern');
    await client.close();
  });

  it('6. Legacy stdio: legacy fallback remains usable', async () => {
    const client = new Client({ name: 'red-test-client', version: '1.0.0' });
    const transport = createStdioTransport();
    await client.connect(transport);
    expect(clientEra(client)).toBe('legacy');

    const tools = await client.listTools();
    expect(tools.tools.map((t) => t.name)).toEqual([...EXPECTED_TOOL_NAMES]);

    await client.close();
  });

  it('7. Direct raw server/discover with MCP-Protocol-Version: 2026-07-28 succeeds; direct legacy initialize returns 2025-11-25', async () => {
    const fetchFn = createTestHandler();
    // Modern discover requires the per-request _meta envelope (SDK v2 inspection).
    const discoverReq = new Request('http://test.local/api/mcp', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json, text/event-stream',
        'MCP-Protocol-Version': '2026-07-28',
        'MCP-Method': 'server/discover',
      },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 1,
        method: 'server/discover',
        params: {
          _meta: {
            'io.modelcontextprotocol/protocolVersion': '2026-07-28',
            'io.modelcontextprotocol/clientInfo': { name: 'test', version: '1.0.0' },
            'io.modelcontextprotocol/clientCapabilities': {},
          },
        },
      }),
    });
    const discoverRes = await fetchFn(discoverReq);
    expect(discoverRes.status).toBe(200);
    const discoverBody = (await readJsonRpcBody(discoverRes)) as {
      result?: CacheableResult & { supportedVersions?: string[] };
    };
    expect(discoverBody.result?.supportedVersions).toContain('2026-07-28');
    // SDK-v2 emits top-level ttlMs/cacheScope on modern discover (no config required).
    expect(discoverBody.result?.ttlMs).toBe(0);
    expect(discoverBody.result?.cacheScope).toBe('private');

    const initReq = new Request('http://test.local/api/mcp', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json, text/event-stream',
      },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 1,
        method: 'initialize',
        params: {
          protocolVersion: '2025-11-25',
          clientInfo: { name: 'test', version: '1.0.0' },
          capabilities: {},
        },
      }),
    });
    const initRes = await fetchFn(initReq);
    expect(initRes.status).toBe(200);
    const initBody = (await readJsonRpcBody(initRes)) as {
      result?: { protocolVersion?: string; serverInfo?: { name?: string } };
    };
    expect(initBody.result?.protocolVersion).toBe('2025-11-25');
    expect(initBody.result?.serverInfo?.name).toBe('flinttrade-docs');
  });

  it('8. Modern responses expose conservative cache defaults (ttlMs=0, cacheScope=private)', async () => {
    const fetchFn = createTestHandler();
    const client = new Client(
      { name: 'red-test-client', version: '1.0.0' },
      { versionNegotiation: { mode: { pin: '2026-07-28' } } },
    );
    const transport = new StreamableHTTPClientTransport(new URL('http://test.local/api/mcp'), {
      fetch: asFetch(fetchFn),
    });
    await client.connect(transport);

    // Real wire shape: top-level ttlMs / cacheScope from SDK-v2 defaults (no cacheHints config).
    const tools = (await client.listTools()) as unknown as CacheableResult & { tools: { name: string }[] };
    const resources = (await client.listResources()) as unknown as CacheableResult;
    const templates = (await client.listResourceTemplates()) as unknown as CacheableResult;
    const prompts = (await client.listPrompts()) as unknown as CacheableResult;
    for (const result of [tools, resources, templates, prompts]) {
      expect(result.ttlMs).toBe(0);
      expect(result.cacheScope).toBe('private');
    }
    expect(tools.tools.map((t) => t.name)).toEqual([...EXPECTED_TOOL_NAMES]);

    await client.close();
  });

  it('9. resources/list, prompts/list, one resources/read, one prompts/get, and one tools/call succeed where the protocol surface supports them', async () => {
    const fetchFn = createTestHandler();
    const client = new Client({ name: 'red-test-client', version: '1.0.0' });
    const transport = new StreamableHTTPClientTransport(new URL('http://test.local/api/mcp'), {
      fetch: asFetch(fetchFn),
    });
    await client.connect(transport);

    await assertExactPublicCatalogue(client);
    await assertListedSlashNamedPackageIsReadable(client);

    const read = await client.readResource({ uri: 'flinttrade://docs/index' });
    expect(read.contents.length).toBeGreaterThan(0);
    const firstContent = read.contents[0] as { text?: string; uri?: string };
    expect(typeof firstContent.text === 'string' || typeof firstContent.uri === 'string').toBe(
      true,
    );
    if (typeof firstContent.text === 'string') {
      expect(firstContent.text.length).toBeGreaterThan(0);
    }

    const prompt = await client.getPrompt({
      name: 'plan_contribution',
      arguments: { goal: 'docs mcp' },
    });
    expect(prompt.messages.length).toBeGreaterThan(0);
    const msg = prompt.messages[0];
    expect(msg.role === 'user' || msg.role === 'assistant').toBe(true);

    const result = await client.callTool({ name: 'list_packages', arguments: {} });
    assertToolTextResult(result);

    await client.close();
  });

  it('10. DELETE/session lifecycle behaviour is absent or 405; no Mcp-Session-Id is required for normal calls', async () => {
    const fetchFn = createTestHandler();
    const deleteReq = new Request('http://test.local/api/mcp', { method: 'DELETE' });
    const deleteRes = await fetchFn(deleteReq);
    expect(deleteRes.status).toBe(405);

    // Normal initialize without Mcp-Session-Id must succeed (stateless transport).
    const initReq = new Request('http://test.local/api/mcp', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json, text/event-stream',
      },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 1,
        method: 'initialize',
        params: {
          protocolVersion: '2025-11-25',
          clientInfo: { name: 'sessionless', version: '1.0.0' },
          capabilities: {},
        },
      }),
    });
    expect(initReq.headers.get('Mcp-Session-Id')).toBeNull();
    const initRes = await fetchFn(initReq);
    expect(initRes.status).toBe(200);
    // Stateless: server must not require clients to round-trip a session id.
    const sessionHeader = initRes.headers.get('Mcp-Session-Id');
    expect(sessionHeader === null || sessionHeader === '').toBe(true);

    const client = new Client({ name: 'red-test-client', version: '1.0.0' });
    const transport = new StreamableHTTPClientTransport(new URL('http://test.local/api/mcp'), {
      fetch: asFetch(fetchFn),
    });
    await client.connect(transport);
    const tools = await client.listTools();
    expect(tools.tools.map((t) => t.name)).toEqual([...EXPECTED_TOOL_NAMES]);
    await client.close();
  });

  it('11. No Apps/Tasks/extensions, no auth challenge, no write/trading tools, no private paths', async () => {
    const fetchFn = createTestHandler();
    const client = new Client({ name: 'red-test-client', version: '1.0.0' });
    const transport = new StreamableHTTPClientTransport(new URL('http://test.local/api/mcp'), {
      fetch: asFetch(fetchFn),
    });
    await client.connect(transport);

    const tools = await client.listTools();
    const toolNames = tools.tools.map((t) => t.name);
    expect(toolNames).toEqual([...EXPECTED_TOOL_NAMES]);
    expect(
      toolNames.some(
        (n) =>
          n.includes('order') ||
          n.includes('trade') ||
          n.includes('broker') ||
          n.includes('app') ||
          n.includes('task') ||
          n.includes('write') ||
          n.includes('kill'),
      ),
    ).toBe(false);

    const resources = await client.listResources();
    const uris = resources.resources.map((r) => r.uri);
    expect(uris.every((uri) => uri.startsWith('flinttrade://'))).toBe(true);
    expect(
      uris.some(
        (uri) =>
          uri.includes('.env') ||
          uri.includes('secret') ||
          uri.includes('credential') ||
          uri.includes('/private/'),
      ),
    ).toBe(false);

    // Unauthenticated initialize must not challenge (no WWW-Authenticate).
    const bareInit = await fetchFn(
      new Request('http://test.local/api/mcp', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json, text/event-stream',
        },
        body: JSON.stringify({
          jsonrpc: '2.0',
          id: 9,
          method: 'initialize',
          params: {
            protocolVersion: '2025-11-25',
            clientInfo: { name: 'anon', version: '1.0.0' },
            capabilities: {},
          },
        }),
      }),
    );
    expect(bareInit.status).toBe(200);
    expect(bareInit.headers.get('WWW-Authenticate')).toBeNull();

    await client.close();
  });

  it('12. Exact deterministic catalogue order and names remain pinned', async () => {
    const fetchFn = createTestHandler();
    const client = new Client({ name: 'red-test-client', version: '1.0.0' });
    const transport = new StreamableHTTPClientTransport(new URL('http://test.local/api/mcp'), {
      fetch: asFetch(fetchFn),
    });
    await client.connect(transport);

    await assertExactPublicCatalogue(client);
    expect([...DOCS_MCP_TOOL_NAMES]).toEqual([...EXPECTED_TOOL_NAMES]);
    expect([...DOCS_MCP_PROMPT_NAMES]).toEqual([...EXPECTED_PROMPT_NAMES]);

    await client.close();
  });

  it('13. MCPBridge and all trading/safety paths are unchanged; stdio spawn failures propagate', async () => {
    // Real safety guard: assertDocsMcpSafety is called in registry and blocks trading names.
    expect(() => assertDocsMcpSafety()).not.toThrow();
    expect(DOCS_MCP_TOOL_NAMES).toEqual(EXPECTED_TOOL_NAMES);
    expect(DOCS_MCP_PROMPT_NAMES).toEqual(EXPECTED_PROMPT_NAMES);

    // MCPBridge is permanently out of scope — file must still exist and not be this pilot's surface.
    const mcpBridgePath = path.join(
      REPO_ROOT,
      'packages/services/ai/src/flinttrade_ai/mcp_bridge.py',
    );
    expect(existsSync(mcpBridgePath)).toBe(true);
    const bridgeSrc = readFileSync(mcpBridgePath, 'utf8');
    expect(bridgeSrc).toMatch(/class\s+MCPBridge|MCPBridge/);
    // Not a wire MCP implementation — no protocol version negotiation surface.
    expect(bridgeSrc).not.toMatch(/2026-07-28|server\/discover|StreamableHTTP/);

    // Spawn of a failing executable must reject — errors are not swallowed.
    const client = new Client({ name: 'red-test-client', version: '1.0.0' });
    const broken = new StdioClientTransport({
      command: process.platform === 'win32' ? 'cmd.exe' : 'false',
      args: process.platform === 'win32' ? ['/c', 'exit', '1'] : [],
      cwd: SITE_ROOT,
      stderr: 'pipe',
    });
    await expect(client.connect(broken)).rejects.toBeTruthy();
  });
});
