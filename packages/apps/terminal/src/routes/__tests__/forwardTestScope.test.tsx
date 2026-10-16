import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ForwardTestSection } from "../LabRoute/ForwardTest";
import { useModeStore } from "@/stores/modeStore";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";

beforeEach(() => {
  useModeStore.setState({ mode: "live" });
  useAuthStore.setState({ status: "logged-in", token: "synthetic-session", username: "operator", sessionGeneration: 400 });
  useBrokerStore.getState().setActiveAccount("native:dhan:live-account");
});
afterEach(() => vi.unstubAllGlobals());

function row(id: string, generation = 1, armed = true) {
  return { run_id: id, actor: "operator", account: `paper:run:${id}`, environment: "paper", kind: "practice", config: { symbols: ["RELIANCE"] },
    generation, entries_armed: armed, state: armed ? "running" : "entries_stopped", uncertain: false, protection: "unverified", native_ready: false,
    books: { positions: [], orders: [], trades: [], pnl: {} } };
}

it("owns two Practice runs beside unchanged Live selection and captures pending exact Stop", async () => {
  const first = row("paper-one");
  const second = row("paper-two");
  const calls: string[] = [];
  const failures: unknown[] = [];
  let release: (() => void) | undefined;
  let stopped = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.replace(/^\/ft-api/, "");
    const key = `${init?.method ?? "GET"} ${path}`;
    calls.push(key);
    try {
      expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer synthetic-session");
      expect(new Headers(init?.headers).has("X-FlintTrade-Mode")).toBe(false);
      let data: unknown;
      if (key === "GET /api/v1/execution-sessions") data = [stopped ? row("paper-one", 2, false) : first, second];
      else if (key === "POST /api/v1/execution-sessions/paper-one/stop") {
        expect(JSON.parse(String(init?.body))).toEqual({ account: first.account, environment: "paper", expected_generation: 1 });
        await new Promise<void>(resolve => { release = resolve; });
        stopped = true; data = row("paper-one", 2, false);
      } else if (key === "GET /api/v1/execution-sessions/paper-one") data = row("paper-one", 2, false);
      else throw new Error(`Unregistered request ${key}`);
      return new Response(JSON.stringify({ status: "success", data }), { status: 200 });
    } catch (error) { failures.push(error); throw error; }
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const mount = () => <QueryClientProvider client={client}><ForwardTestSection /></QueryClientProvider>;
  const view = render(mount());
  const one = await screen.findByRole("region", { name: "Practice run paper-one" });
  expect(screen.getByRole("region", { name: "Practice run paper-two" })).toBeVisible();
  fireEvent.click(within(one).getByRole("button", { name: "Stop entries" }));
  await waitFor(() => expect(release).toBeTypeOf("function"));
  act(() => useBrokerStore.getState().setActiveAccount("native:upstox:another-live"));
  view.unmount(); // UI closure is not a stop/cancel/Close command.
  await act(async () => { release?.(); });
  render(mount());
  expect(await screen.findByText("entries_stopped")).toBeVisible();
  expect(within(screen.getByRole("region", { name: "Practice run paper-two" })).getByText("running")).toBeVisible();
  expect(useModeStore.getState().mode).toBe("live");
  expect(useBrokerStore.getState().activeAccountId).toBe("native:upstox:another-live");
  expect(calls.filter(call => call.startsWith("POST"))).toEqual(["POST /api/v1/execution-sessions/paper-one/stop"]);
  expect(failures).toEqual([]);
});

it.each(["practice", "strategy"])("starts a new %s Practice run with immutable identity and readback, never name-only dispatch", async (kind) => {
  const failures: unknown[] = [];
  let created: ReturnType<typeof row> | undefined;
  const posts: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.replace(/^\/ft-api/, "");
    const method = init?.method ?? "GET";
    try {
      let data: unknown;
      if (method === "GET" && path === "/api/v1/execution-sessions") data = created ? [created] : [];
      else if (method === "POST" && path === "/api/v1/execution-sessions") {
        posts.push(path);
        const body = JSON.parse(String(init?.body));
        expect(body.kind).toBe(kind); expect(body.config.symbols).toEqual(["RELIANCE"]);
        if (kind === "strategy") expect(body.config.strategy).toBe("registered-strategy");
        expect(body.account).toBeUndefined(); expect(body.mode).toBeUndefined();
        created = { ...row(body.run_id, 0, false), kind, config: body.config, state: "ready" }; data = created;
      } else if (created && method === "POST" && path === `/api/v1/execution-sessions/${created.run_id}/start`) {
        posts.push(path); expect(JSON.parse(String(init?.body))).toEqual({ account: created.account, environment: "paper", expected_generation: 0 });
        created = { ...created, generation: 1, entries_armed: true, state: "running" }; data = created;
      } else if (created && method === "GET" && path === `/api/v1/execution-sessions/${created.run_id}`) data = created;
      else throw new Error(`Unregistered request ${method} ${path}`);
      return new Response(JSON.stringify({ status: "success", data }), { status: 200 });
    } catch (error) { failures.push(error); throw error; }
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ForwardTestSection /></QueryClientProvider>);
  fireEvent.change(screen.getByLabelText("Symbols"), { target: { value: "RELIANCE" } });
  if (kind === "strategy") fireEvent.change(screen.getByLabelText("Registered strategy (optional)"), { target: { value: "registered-strategy" } });
  fireEvent.click(screen.getByRole("button", { name: "Start Practice run" }));
  expect(await screen.findByText("running")).toBeVisible();
  expect(posts).toHaveLength(2);
  expect(useModeStore.getState().mode).toBe("live");
  expect(useBrokerStore.getState().activeAccountId).toBe("native:dhan:live-account");
  expect(failures).toEqual([]);
});
