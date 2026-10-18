import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";
import { ForwardTestSection } from "../ForwardTest";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(nextResolve => { resolve = nextResolve; });
  return { promise, resolve };
}
function row(id: string, actor: string, stopped = false) {
  return { run_id: id, actor, account: `paper:run:${id}`, environment: "paper", kind: "practice", config: { symbols: ["RELIANCE"] },
    generation: stopped ? 2 : 1, entries_armed: !stopped, state: stopped ? "entries_stopped" : "running", uncertain: false,
    protection: "unverified", native_ready: false,
    books: { positions: [], orders: [], trades: stopped ? [{ symbol: "ALICE-PRIVATE-FILL", pnl: 125 }] : [], pnl: {} } };
}
function response(data: unknown) { return new Response(JSON.stringify({ status: "success", data }), { status: 200 }); }

beforeEach(() => {
  useAuthStore.setState({ status: "logged-in", token: "token-1", username: "alice", sessionGeneration: 7 });
  useModeStore.setState({ mode: "live" });
});
afterEach(() => vi.unstubAllGlobals());

describe("ForwardTestSection", () => {
  it("does not publish a stopped summary after the auth session changes during trade loading", async () => {
    const pendingTrades = deferred<Response>();
    const readEntered = deferred<void>();
    const calls: string[] = [];
    const failures: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.replace(/^\/ft-api/, "");
      const bearer = new Headers(init?.headers).get("Authorization");
      const key = `${init?.method} ${path} ${bearer}`;
      calls.push(key);
      try {
        if (key === "GET /api/v1/execution-sessions Bearer token-1") return response([row("paper-alice", "alice")]);
        if (key === "POST /api/v1/execution-sessions/paper-alice/stop Bearer token-1") {
          expect(JSON.parse(String(init?.body))).toEqual({ account: "paper:run:paper-alice", environment: "paper", expected_generation: 1 });
          return response(row("paper-alice", "alice", true));
        }
        if (key === "GET /api/v1/execution-sessions/paper-alice Bearer token-1") {
          readEntered.resolve(); return await pendingTrades.promise;
        }
        if (key === "GET /api/v1/execution-sessions Bearer token-2") return response([row("paper-bob", "bob")]);
        throw new Error(`Unregistered exact transport ${key}`);
      } catch (error) { failures.push(error); throw error; }
    }));
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><ForwardTestSection /></QueryClientProvider>);
    const alice = await screen.findByRole("region", { name: "Practice run paper-alice" });
    await act(async () => {
      fireEvent.click(within(alice).getByRole("button", { name: "Stop entries" }));
      await readEntered.promise; // Prove the held trade/P&L read belongs to Alice's accepted exact Stop.
    });
    try {
    act(() => useAuthStore.setState({ token: "token-2", username: "bob", sessionGeneration: 8 }));
    const bob = await screen.findByRole("region", { name: "Practice run paper-bob" });
    expect(screen.queryByText(/Pending exact run: paper-alice/)).not.toBeInTheDocument();
    await act(async () => { pendingTrades.resolve(response(row("paper-alice", "alice", true))); await pendingTrades.promise; });
    await waitFor(() => expect(within(bob).getByRole("button", { name: "Stop entries" })).toBeEnabled());
    expect(within(bob).getByText("running")).toBeVisible();
    expect(screen.queryByText("Session Summary")).not.toBeInTheDocument();
    expect(screen.queryByText("entries_stopped")).not.toBeInTheDocument();
    expect(screen.queryByText(/ALICE-PRIVATE-FILL/)).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Practice run paper-alice" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(calls.filter(call => call.startsWith("POST"))).toEqual(["POST /api/v1/execution-sessions/paper-alice/stop Bearer token-1"]);
    expect(calls.filter(call => call.endsWith("Bearer token-2"))).toEqual(["GET /api/v1/execution-sessions Bearer token-2"]);
    expect(useModeStore.getState().mode).toBe("live");
    expect(failures).toEqual([]);
    } finally {
      await act(async () => { pendingTrades.resolve(response(row("paper-alice", "alice", true))); await pendingTrades.promise; });
    }
  });
});
