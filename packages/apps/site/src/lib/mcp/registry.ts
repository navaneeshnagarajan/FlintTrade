import { McpServer, ResourceTemplate } from '@modelcontextprotocol/server';
import { createMcpHandler } from 'mcp-handler';
import { z } from 'zod';

import { APP_VERSION } from '../version';
import {
  DOCS_MCP_PROMPT_NAMES,
  DOCS_MCP_TOOL_NAMES,
  assertDocsMcpSafety,
  explainRepoPath,
  getDoc,
  listPackages,
  makeContributionPlan,
  recommendTests,
  searchDocs,
} from './capabilities';
import { docsIndex } from './data';

function textResult(text: string) {
  return {
    content: [{ type: 'text' as const, text }],
  };
}

function jsonText(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

/**
 * Register the exact public FlintTrade docs MCP catalogue on an SDK-v2 server.
 * Order is load-bearing for listTools / listPrompts / static resource prefixes.
 */
export function registerFlintDocsMcp(server: McpServer): void {
  assertDocsMcpSafety();

  // Tools (exact order)
  server.registerTool(
    'search_docs',
    {
      title: 'Search FlintTrade docs',
      description: 'Search FlintTrade documentation and package README content for contribution and development context.',
      inputSchema: z.object({
        query: z.string().min(1),
        area: z.string().optional(),
      }),
    },
    async ({ query, area }) => textResult(jsonText(searchDocs(query, area))),
  );

  server.registerTool(
    'get_doc',
    {
      title: 'Read a FlintTrade doc',
      description: 'Return one generated documentation entry by slug.',
      inputSchema: z.object({
        slug: z.string().min(1),
      }),
    },
    async ({ slug }) => {
      const doc = getDoc(slug);
      if (!doc) return textResult(`No FlintTrade document found for slug "${slug}".`);

      return textResult(`# ${doc.title}\n\nSource: ${doc.sourcePath}\n\n${doc.content}`);
    },
  );

  server.registerTool(
    'list_packages',
    {
      title: 'List FlintTrade packages',
      description: 'List package names, descriptions, docs URLs, and README source paths.',
    },
    async () => textResult(jsonText(listPackages())),
  );

  server.registerTool(
    'explain_repo_path',
    {
      title: 'Explain a FlintTrade repo path',
      description: 'Explain which subsystem owns a repository path and where to start reading.',
      inputSchema: z.object({
        path: z.string().min(1),
      }),
    },
    async ({ path }) => textResult(explainRepoPath(path)),
  );

  server.registerTool(
    'recommend_tests',
    {
      title: 'Recommend tests for changed paths',
      description: 'Suggest focused validation commands based on changed FlintTrade paths.',
      inputSchema: z.object({
        changed_paths: z.array(z.string()).min(1),
      }),
    },
    async ({ changed_paths }) => textResult(jsonText(recommendTests(changed_paths))),
  );

  server.registerTool(
    'make_contribution_plan',
    {
      title: 'Make a contribution plan',
      description: 'Draft a concise contribution plan from FlintTrade docs for a stated development goal.',
      inputSchema: z.object({
        goal: z.string().min(1),
      }),
    },
    async ({ goal }) => textResult(makeContributionPlan(goal)),
  );

  // Static resources (exact first four; templates append generated docs/packages)
  server.registerResource(
    'docs-index',
    'flinttrade://docs/index',
    {
      title: 'FlintTrade docs index',
      description: 'Generated index of FlintTrade docs, packages, and common commands.',
      mimeType: 'application/json',
    },
    async (uri) => ({
      contents: [{ uri: uri.href, mimeType: 'application/json', text: jsonText(docsIndex) }],
    }),
  );

  server.registerResource(
    'packages',
    'flinttrade://packages',
    {
      title: 'FlintTrade packages',
      description: 'Generated package index sourced from package README files.',
      mimeType: 'application/json',
    },
    async (uri) => ({
      contents: [{ uri: uri.href, mimeType: 'application/json', text: jsonText(listPackages()) }],
    }),
  );

  server.registerResource(
    'contributing',
    'flinttrade://contributing',
    {
      title: 'FlintTrade contributing guide',
      description: 'Contributor-oriented documentation entry.',
      mimeType: 'text/markdown',
    },
    async (uri) => {
      const doc = getDoc('developer-guide');
      return {
        contents: [{ uri: uri.href, mimeType: 'text/markdown', text: doc?.content ?? 'Developer guide unavailable.' }],
      };
    },
  );

  server.registerResource(
    'commands',
    'flinttrade://commands',
    {
      title: 'FlintTrade commands',
      description: 'Common development commands surfaced by the docs MCP.',
      mimeType: 'application/json',
    },
    async (uri) => ({
      contents: [{ uri: uri.href, mimeType: 'application/json', text: jsonText(docsIndex.commands) }],
    }),
  );

  // Resource templates (exact)
  server.registerResource(
    'doc',
    new ResourceTemplate('flinttrade://docs/{slug}', {
      list: async () => ({
        resources: docsIndex.docs.map((doc) => ({
          uri: `flinttrade://docs/${encodeURIComponent(doc.slug)}`,
          name: doc.slug,
          title: doc.title,
          description: doc.description,
          mimeType: 'text/markdown',
        })),
      }),
    }),
    {
      title: 'FlintTrade doc by slug',
      description: 'Read a generated doc by slug. Use encoded slashes for nested slugs.',
      mimeType: 'text/markdown',
    },
    async (uri, variables) => {
      const slug = decodeURIComponent(String(variables.slug));
      const doc = getDoc(slug);
      return {
        contents: [{
          uri: uri.href,
          mimeType: 'text/markdown',
          text: doc ? `# ${doc.title}\n\nSource: ${doc.sourcePath}\n\n${doc.content}` : `No document found for ${slug}.`,
        }],
      };
    },
  );

  server.registerResource(
    'package',
    new ResourceTemplate('flinttrade://packages/{name}', {
      list: async () => ({
        resources: listPackages().map((pkg) => ({
          uri: `flinttrade://packages/${pkg.name}`,
          name: pkg.name,
          title: pkg.title,
          description: pkg.description,
          mimeType: 'text/markdown',
        })),
      }),
    }),
    {
      title: 'FlintTrade package by name',
      description: 'Read a package README by package name.',
      mimeType: 'text/markdown',
    },
    async (uri, variables) => {
      const pkg = listPackages().find((entry) => entry.name === String(variables.name));
      return {
        contents: [{
          uri: uri.href,
          mimeType: 'text/markdown',
          text: pkg ? `# ${pkg.title}\n\nSource: ${pkg.sourcePath}\n\n${pkg.content}` : `No package found for ${String(variables.name)}.`,
        }],
      };
    },
  );

  // Prompts (exact order)
  server.registerPrompt(
    'plan_contribution',
    {
      title: 'Plan a FlintTrade contribution',
      description: 'Create a repo-grounded contribution plan from a goal.',
      argsSchema: z.object({ goal: z.string().min(1) }),
    },
    ({ goal }) => ({
      messages: [{
        role: 'user',
        content: { type: 'text', text: makeContributionPlan(goal) },
      }],
    }),
  );

  server.registerPrompt(
    'add_terminal_widget',
    {
      title: 'Add a terminal widget',
      description: 'Guide an agent through adding a React terminal widget.',
      argsSchema: z.object({ widget_name: z.string().min(1) }),
    },
    ({ widget_name }) => ({
      messages: [{
        role: 'user',
        content: {
          type: 'text',
          text: [
            `Plan a FlintTrade terminal widget named ${widget_name}.`,
            'Use docs/DEVELOPER_GUIDE.md and packages/apps/terminal/README.md.',
            'Keep the widget functional, registered as a FlexLayout panel, tested with Vitest, and visually consistent with the existing terminal.',
          ].join('\n'),
        },
      }],
    }),
  );

  server.registerPrompt(
    'add_python_feature',
    {
      title: 'Add a Python feature',
      description: 'Guide an agent through adding a scoped Python package feature.',
      argsSchema: z.object({ package_name: z.string().min(1), goal: z.string().min(1) }),
    },
    ({ package_name, goal }) => ({
      messages: [{
        role: 'user',
        content: {
          type: 'text',
          text: [
            `Plan a Python feature in packages/${package_name}: ${goal}`,
            'Use package README context, public type hints, Google-style docstrings, Ruff, and focused pytest coverage.',
            `Start validation with python -m pytest packages/${package_name}/tests/ -v --import-mode=importlib.`,
          ].join('\n'),
        },
      }],
    }),
  );

  server.registerPrompt(
    'update_docs_for_change',
    {
      title: 'Update docs for a change',
      description: 'Guide an agent through keeping docs in sync with a repo change.',
      argsSchema: z.object({ changed_paths: z.array(z.string()).min(1) }),
    },
    ({ changed_paths }) => ({
      messages: [{
        role: 'user',
        content: {
          type: 'text',
          text: [
            'Plan documentation updates for these FlintTrade paths:',
            ...changed_paths.map((changedPath) => `- ${changedPath}`),
            '',
            'Check docs/README.md, docs/DEVELOPER_GUIDE.md, docs/API.md, and the affected package README before editing.',
          ].join('\n'),
        },
      }],
    }),
  );

  void DOCS_MCP_TOOL_NAMES;
  void DOCS_MCP_PROMPT_NAMES;
}

export type FlintDocsMcpServerOptions = {
  /** Server name reported during initialize / discover. */
  name?: string;
  /** Server version; defaults to APP_VERSION from ../version. */
  version?: string;
};

/**
 * Fresh SDK-v2 McpServer with the public docs catalogue registered.
 * Used by stdio, HTTP factory, and tests. Dual-era: same factory serves
 * modern (`server/discover`) and legacy (`initialize`) openings.
 *
 * Cache posture: rely on SDK-v2 fixed defaults (ttlMs=0, cacheScope=private)
 * — no cacheHints configuration in this compatibility slice.
 */
export function createFlintDocsMcpServer(options: FlintDocsMcpServerOptions = {}): McpServer {
  const server = new McpServer({
    name: options.name ?? 'flinttrade-docs',
    version: options.version ?? APP_VERSION,
  });
  registerFlintDocsMcp(server);
  return server;
}

/**
 * Web-standard callable request handler for the docs MCP.
 *
 * mcp-handler@2.1 returns `(request: Request) => Promise<Response>`.
 * This wrapper also accepts the WHATWG `fetch(input, init)` shape so
 * StreamableHTTPClientTransport can pass it as `fetch` without 500s.
 * It is intentionally a function (callable), not an object with `.fetch`.
 *
 * Errors from the underlying handler are not swallowed — they reject the
 * returned promise so connect/call failures propagate to the client.
 */
export type FlintDocsMcpHttpHandler = {
  (input: Request): Promise<Response>;
  (input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
};

export function createFlintDocsMcpHttpHandler(
  options: FlintDocsMcpServerOptions = {},
): FlintDocsMcpHttpHandler {
  const serverInfo = {
    name: options.name ?? 'flinttrade-docs',
    version: options.version ?? APP_VERSION,
  };

  const mcpHandler = createMcpHandler(
    (server) => {
      registerFlintDocsMcp(server);
    },
    { serverInfo },
  );

  const handler = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const request = input instanceof Request ? input : new Request(input, init);
    try {
      return await mcpHandler(request);
    } catch (error) {
      // Propagate connection/handler failures; never convert to empty success.
      if (error instanceof Error) throw error;
      throw new Error(`Docs MCP HTTP handler failed: ${String(error)}`);
    }
  };

  return handler as FlintDocsMcpHttpHandler;
}
