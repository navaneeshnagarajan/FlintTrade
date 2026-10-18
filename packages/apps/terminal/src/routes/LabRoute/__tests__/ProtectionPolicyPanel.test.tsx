import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { ForwardTestSection } from "../ForwardTest";

const scope = { run_id: "r29-protected", actor: "operator", account: "paper:run:r29-protected", environment: "paper" };
const row = { ...scope, kind: "practice", config: {}, generation: 1, entries_armed: true, state: "running", uncertain: false, protection: "unverified", native_ready: false, books: { positions: [], orders: [], trades: [], pnl: {} } };
const policy = { policy_revision: "synthetic-reviewed-v1", valid_until: 2000000000, position: { symbol: "TEST", exchange: "NSE", product: "CNC", entry_order_ids: ["exact-entry"], quantity: 2 }, hedge_scope: [], risk_policy: "unhedged-cash-reduction-only", max_quantity: 2, max_notional: 400, read: { selector: "synthetic:quotes", valid_until: 2000000000, max_reads: 5, max_age_seconds: 10 } };
const inputs = { policy_revision: "synthetic-reviewed-v1", valid_until: "2000000000", "position.symbol": "TEST", "position.exchange": "NSE", "position.product": "CNC", "position.entry_order_ids": "exact-entry", "position.quantity": "2", max_quantity: "2", max_notional: "400", "read.selector": "synthetic:quotes", "read.valid_until": "2000000000", "read.max_reads": "5", "read.max_age_seconds": "10" };
const base = "/api/v1/protection/grants";
function readback(revision = 0, retired = false) { return { scope, revision, policy: revision ? policy : null, authority_state: revision ? retired ? "retired" : "active" : "not_issued", usage: revision ? { reads: 0, quantity_used: 0, notional_used: 0 } : null, duty: { state: revision ? "retained" : "not_granted", remaining_quantity: revision ? 2 : null, reconciliation_required: false, attempts: [] }, supervision: "unavailable" }; }
const response = (data: unknown, status = 200) => new Response(JSON.stringify({ status: "success", data }), { status });
beforeEach(() => useAuthStore.setState({ status: "logged-in", username: "operator", token: "synthetic-protection", sessionGeneration: 2900 }));
afterEach(() => vi.unstubAllGlobals());
function mount() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ForwardTestSection /></QueryClientProvider>); }

it("mounts exact protection approval and revoke while retaining unresolved duty and unavailable supervision", async () => {
  let revision = 0; let retired = false;
  const calls: { method?: string; path: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.replace(/^\/ft-api/, ""); const body: unknown = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ path, method: init?.method, body });
    if (path === "/api/v1/execution-sessions") return response([row]);
    if (path === `${base}/${scope.run_id}`) return response(readback(revision, retired));
    if (path === base && init?.method === "POST") { expect(body).toEqual({ run_id: scope.run_id, expected_revision: 0, policy }); revision = 1; return response({ scope, revision, policy }, 201); }
    if (path === `${base}/${scope.run_id}/revoke`) { expect(body).toEqual({ expected_revision: 1 }); revision = 2; retired = true; return response({ scope, revision, revoked: true, duty_retained: true }); }
    throw new Error("Unregistered protection transport");
  }));
  mount(); fireEvent.click(await screen.findByRole("button", { name: "Protection policy" }));
  await screen.findByText(/Authority: not_issued/);
  expect(screen.getByText(/no independent restart protection/i)).toBeVisible();
  for (const [name, value] of Object.entries(inputs)) fireEvent.change(document.querySelector(`[name="${name}"]`)!, { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "Review protection policy" }));
  expect(calls.filter(call => call.method === "POST")).toEqual([]);
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Approve exact protection policy" })));
  await screen.findByText(/Authority: active/);
  expect(screen.getByText(/Supervision: unavailable/)).toBeVisible();
  expect(screen.getByText(/Duty: retained/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Review protection revocation" }));
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Confirm protection revocation" })));
  await screen.findByText(/Authority: retired/);
  expect(screen.getByText(/Duty: retained/)).toBeVisible();
  expect(screen.getByText(/Remaining quantity: 2/)).toBeVisible();
  expect(calls.filter(call => call.path.startsWith(base)).map(call => `${call.method} ${call.path}`)).toEqual([
    `GET ${base}/${scope.run_id}`, `POST ${base}`, `GET ${base}/${scope.run_id}`, `POST ${base}/${scope.run_id}/revoke`, `GET ${base}/${scope.run_id}`,
  ]);
});

it("treats custody failure as unknown not grantless and issues no navigation control", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method} ${url}`);
    if (url.endsWith("/execution-sessions")) return response([row]);
    return new Response(JSON.stringify({ status: "unavailable", code: "protection_custody_unavailable" }), { status: 503 });
  }));
  mount(); fireEvent.click(await screen.findByRole("button", { name: "Protection policy" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/unavailable/i));
  expect(screen.queryByText(/Authority: not_issued/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Approve exact protection policy" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Hide protection policy" }));
  expect(calls.every(call => call.startsWith("GET "))).toBe(true);
});
