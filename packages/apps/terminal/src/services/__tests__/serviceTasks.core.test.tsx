import { readFileSync } from "node:fs";
import snapshot from "./serviceTasks.core-fixture.json";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { dispatchServiceTask, readServiceTask, type ServiceTask, type ServiceTaskReceipt } from "../serviceTasks";
import ModelRoutingPanel from "@/components/help/ModelRoutingPanel";
import { knowledgeTransport, response, seedKnowledgeSession } from "./knowledgeTestUtils";

type Fixture = { cases: { task: ServiceTask; post: ServiceTaskReceipt; get: ServiceTaskReceipt }[];
  connections: unknown; etag: string; catalogue: unknown; procedure: unknown;
  provider_calls: number; task_posts: number; task_gets: number };
// Checked-in bytes were produced by serviceTasks.core-fixture.py, not a DTO
// approximation. The isolated cross-language gate regenerates them against the
// current normal factory; ordinary frontend-only CI needs no Python runtime.
const fixture: Fixture = process.env["R25_TASK_DTOS"]
  ? JSON.parse(readFileSync(process.env["R25_TASK_DTOS"], "utf8")) as Fixture : snapshot as Fixture;
const base = "/ft-api/v1/services/connections";
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("reconciles genuine normal-factory POST/GET DTOs for Unicode, escaping and empty text", async () => {
  seedKnowledgeSession();
  expect(fixture.provider_calls).toBe(4); expect(fixture.task_posts).toBe(4); expect(fixture.task_gets).toBe(4);
  const io = knowledgeTransport();
  for (const { task, post, get } of fixture.cases) {
    io.routes.set(`POST ${base}/tasks`, init => { expect(JSON.parse(String(init.body))).toEqual(task); return response(post); });
    io.routes.set(`GET ${base}/tasks/${task.request_id}`, () => response(get));
    expect(get).not.toHaveProperty("output");
    expect(await dispatchServiceTask(task)).toEqual(post);
    expect(await readServiceTask(task.request_id)).toEqual(get);
  }
  expect(io.requests.filter(request => request.init.method === "POST")).toHaveLength(4);
  expect(io.requests.filter(request => request.init.method === "GET")).toHaveLength(8);
  io.assertClean();
});

it("renders genuine core text through the public panel and preserves it on exact manual read", async () => {
  seedKnowledgeSession();
  const { task, post, get } = fixture.cases[0];
  const io = knowledgeTransport();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  io.routes.set(`GET ${base}`, () => new Response(JSON.stringify(fixture.connections), { headers: { ETag: fixture.etag } }));
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response(fixture.catalogue));
  io.routes.set("GET /ft-api/v1/knowledge/skills/risk_management", () => response(fixture.procedure));
  io.routes.set(`POST ${base}/tasks`, init => { expect(JSON.parse(String(init.body))).toEqual(task); return response(post); });
  io.routes.set(`GET ${base}/tasks/${task.request_id}`, () => response(get));
  vi.spyOn(crypto, "randomUUID").mockReturnValue(task.request_id as `${string}-${string}-${string}-${string}-${string}`);
  const errors = vi.spyOn(console, "error");
  const fill = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
  try {
    render(<QueryClientProvider client={client}><ModelRoutingPanel /></QueryClientProvider>);
    await screen.findByRole("option", { name: "Synthetic R25 · llm:openrouter" });
    fireEvent.click(screen.getByText("Choose canonical knowledge"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Read procedure risk_management" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Read procedure risk_management" }));
    await screen.findByLabelText("Complete procedure body");
    fireEvent.click(screen.getByRole("button", { name: "Select this procedure" }));
    await screen.findByRole("button", { name: "Unselect this procedure" });
    fill("Task connection", task.selection!.connection_id); fill("Task effort", task.selection!.effort);
    fill("Task deadline", String(task.deadline_ms)); fill("Task output limit", String(task.max_output_tokens)); fill("Advisory task", task.prompt);
    fireEvent.click(screen.getByRole("button", { name: "Send advisory task" }));
    await screen.findByText(post.output!);
    fireEvent.click(screen.getByRole("button", { name: "Read durable receipt" }));
    await waitFor(() => expect(io.requests.filter(r => r.path.includes("/tasks/")).length).toBe(2));
    await waitFor(() => expect(screen.getByRole("button", { name: "Read durable receipt" })).toBeEnabled());
    expect(screen.getByText(post.output!)).toBeVisible();
    expect(JSON.stringify(client.getQueryCache().getAll().map(q => q.state.data))).not.toContain(post.output!);
    expect(io.requests.filter(r => r.path.endsWith("/skills"))).toHaveLength(4);
    expect(io.requests.filter(r => r.path.endsWith("/skills/risk_management"))).toHaveLength(2);
    expect(io.requests.filter(r => r.init.method === "POST")).toHaveLength(1);
    expect(errors.mock.calls).toEqual([]);
    await act(async () => { cleanup(); client.clear(); });
    io.assertClean();
  } finally { cleanup(); client.clear(); }
});
