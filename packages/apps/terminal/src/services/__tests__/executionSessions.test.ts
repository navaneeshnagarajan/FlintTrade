import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { controlExecutionSession, createPaperSession, readExecutionSession, type ExecutionSessionRecord } from "../executionSessions";

beforeEach(() => useAuthStore.setState({ status: "logged-in", token: "synthetic-r20", username: "operator", sessionGeneration: 900 }));
afterEach(() => vi.unstubAllGlobals());
const row = (id: string): ExecutionSessionRecord => ({ run_id: id, actor: "operator", account: `paper:run:${id}`, environment: "paper", kind: "practice",
  config: { symbols: ["RELIANCE"] }, generation: 0, entries_armed: false, state: "ready", uncertain: false, protection: "unverified", native_ready: false,
  books: { positions: [], orders: [], trades: [], pnl: {} } });
const response = (data: unknown) => new Response(JSON.stringify({ status: "success", data }), { status: 200 });

it("reads exact status after malformed acknowledgement without replaying the mutation", async () => {
  const target = row("unknown-ack");
  const calls: string[] = [];
  const failures: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method} ${url.replace(/^\/ft-api/, "")}`;
    calls.push(key);
    if (key === "POST /api/v1/execution-sessions/unknown-ack/start") return response({});
    if (key === "GET /api/v1/execution-sessions/unknown-ack") return response({ ...target, generation: 1, entries_armed: true, state: "running" });
    failures.push(key); throw new Error(`Unregistered ${key}`);
  }));
  await expect(controlExecutionSession(target, "start")).rejects.toThrow(/unknown/);
  expect(calls).toEqual(["POST /api/v1/execution-sessions/unknown-ack/start", "GET /api/v1/execution-sessions/unknown-ack"]);
  await expect(controlExecutionSession(target, "start")).rejects.toThrow(/already sent/);
  expect(calls).toHaveLength(2); expect(failures).toEqual([]);
});

it("does not accept a different runtime kind for a registered strategy request", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method} ${url.replace(/^\/ft-api/, "")}`; calls.push(key);
    if (!["POST /api/v1/execution-sessions", "GET /api/v1/execution-sessions/wrong-kind"].includes(key)) throw new Error(key);
    return response(row("wrong-kind"));
  }));
  await expect(createPaperSession("wrong-kind", { symbols: ["RELIANCE"], strategy: "registered" })).rejects.toThrow(/identity|configuration|kind/);
  expect(calls).toHaveLength(2);
});

it("retires a held response after logout/relogin even with the same username", async () => {
  let release: ((value: Response) => void) | undefined;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(resolve => { release = resolve; })));
  const pending = readExecutionSession("old-session");
  const refused = expect(pending).rejects.toThrow(/retired/);
  expect(release).toBeTypeOf("function");
  useAuthStore.setState({ sessionGeneration: 901, token: "synthetic-new-session" });
  release?.(response(row("old-session")));
  await refused;
  expect(fetch).toHaveBeenCalledTimes(1);
});
