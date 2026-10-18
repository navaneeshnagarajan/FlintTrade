import { StrictMode } from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import KnowledgeLibrary from "../KnowledgeSelector";
import ModelRoutingPanel from "../ModelRoutingPanel";
import { SCOPE, knowledgeTransport, response, row, seedKnowledgeSession } from "@/services/__tests__/knowledgeTestUtils";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("notifies sibling real knowledge consumers outside query construction during render", async () => {
  seedKnowledgeSession();
  const io = knowledgeTransport();
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope: SCOPE, skills: [row()] }));
  io.routes.set("GET /ft-api/v1/services/connections", () => new Response(JSON.stringify({ connections: [] }), { headers: { ETag: `"${"a".repeat(64)}"` } }));
  const errors = vi.spyOn(console, "error"); // Call through: never suppress React's warning.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  try {
    render(<StrictMode><QueryClientProvider client={client}><MemoryRouter><KnowledgeLibrary /><ModelRoutingPanel /></MemoryRouter></QueryClientProvider></StrictMode>);
    await waitFor(() => expect(screen.getAllByRole("button", { name: /Read procedure/, hidden: true })).toHaveLength(2));
    await waitFor(() => expect(screen.getAllByRole("button", { name: /Read procedure/, hidden: true }).every(button => !button.hasAttribute("disabled"))).toBe(true));
    expect(errors.mock.calls).toEqual([]);
    expect(io.requests.filter(request => request.path.endsWith("/skills"))).toHaveLength(1);
    io.assertClean();
  } finally { cleanup(); client.clear(); }
});
