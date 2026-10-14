import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { useConnectionStore } from "@/stores/connectionStore";
import SandboxControls from "../SandboxControls";

// Exact synthetic envelopes from data/sandbox_routes.py, not hook readiness.
const policy = {
  starting_capital: 1_000_000,
  equity_leverage: 1,
  futures_leverage: 1,
  option_buy_leverage: 1,
  option_sell_leverage: 1,
  squareoff_time: "15:15",
  mcx_squareoff_time: "23:25",
};
const validStatus = {
  status: "success",
  data: { capital: 1_000_000, initial_capital: 1_000_000, pnl: 0, gross_pnl: 0, charges: 0, trades_count: 0 },
};
const validPolicy = { status: "success", data: { config: policy } };
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});
const requests: string[] = [];
const unexpected: string[] = [];
const clients: QueryClient[] = [];
const originalAuth = useAuthStore.getState();
const originalConnection = useConnectionStore.getState();

function mountReads(status: () => Response, config: () => Response, save?: (init: RequestInit) => Response) {
  const handlers = new Map<string, (init: RequestInit) => Response>([
    ["GET /ft-api/v1/sandbox/status", status],
    ["GET /ft-api/v1/sandbox/config", config],
  ]);
  if (save) handlers.set("POST /ft-api/v1/sandbox/config", save);
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const key = `${init.method ?? "GET"} ${String(input)}`;
    requests.push(key);
    try {
      expect(init.headers).toEqual({
        Authorization: "Bearer synthetic-sandbox-session",
        ...(init.method === "POST" ? { "Content-Type": "application/json" } : {}),
      });
      const handler = handlers.get(key);
      if (!handler) throw new Error(`Unregistered request: ${key}`);
      return handler(init);
    } catch (error) {
      unexpected.push(String(error));
      throw error;
    }
  }));
  const client = new QueryClient();
  clients.push(client);
  render(<QueryClientProvider client={client}><SandboxControls /></QueryClientProvider>);
}

beforeEach(() => {
  requests.length = 0;
  unexpected.length = 0;
  useAuthStore.setState({ status: "logged-in", token: "synthetic-sandbox-session" });
  useConnectionStore.setState({ apiKey: "" });
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach(client => client.clear());
  vi.unstubAllGlobals();
  useAuthStore.setState(originalAuth);
  useConnectionStore.setState(originalConnection);
  expect(unexpected).toEqual([]);
});

it("does not expose editable invented policy or zero capital when the real reads fail", async () => {
  const unavailable = () => response({ status: "error", message: "sandbox_unavailable" }, 503);
  mountReads(unavailable, unavailable);
  await vi.waitFor(() => expect(requests).toHaveLength(4), { timeout: 2500 });
  expect(screen.queryByLabelText("Starting capital")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Save Policy" })).not.toBeInTheDocument();
  expect(await screen.findByText(/Practice policy unavailable/)).toBeVisible();
  expect(await screen.findByText(/Sandbox balance and P&L unavailable/)).toBeVisible();
  expect(screen.queryByText("₹0.00")).not.toBeInTheDocument();
  expect(requests.filter(key => key === "GET /ft-api/v1/sandbox/status")).toHaveLength(2);
  expect(requests.filter(key => key === "GET /ft-api/v1/sandbox/config")).toHaveLength(2);
});

it("refuses a malformed successful status instead of publishing a zero balance", async () => {
  mountReads(() => response({ ...validStatus, data: {} }), () => response(validPolicy));
  expect(await screen.findByText(/Sandbox balance and P&L unavailable/, {}, { timeout: 2500 })).toBeVisible();
  expect(screen.queryByText("₹0.00")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Starting capital")).toHaveValue(policy.starting_capital);
  expect(requests.filter(key => key === "GET /ft-api/v1/sandbox/status")).toHaveLength(2);
  expect(requests.filter(key => key === "GET /ft-api/v1/sandbox/config")).toHaveLength(1);
});

it.each([
  { name: "error envelope", body: { ...validStatus, status: "error" } },
  { name: "missing envelope status", body: { data: validStatus.data } },
  ...Object.keys(validStatus.data).map(field => ({
    name: `missing ${field}`,
    body: { ...validStatus, data: { ...validStatus.data, [field]: undefined } },
  })),
  { name: "string balance", body: { ...validStatus, data: { ...validStatus.data, capital: "0" } } },
  { name: "null P&L", body: { ...validStatus, data: { ...validStatus.data, pnl: null } } },
  { name: "fractional trade count", body: { ...validStatus, data: { ...validStatus.data, trades_count: 0.5 } } },
])("refuses $name without replacing unavailable evidence with zero", async ({ body }) => {
  mountReads(() => response(body), () => response(validPolicy));
  expect(await screen.findByText(/Sandbox balance and P&L unavailable/, {}, { timeout: 2500 })).toBeVisible();
  expect(screen.queryByText("₹0.00")).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/P&L:/)).not.toBeInTheDocument();
  expect(requests.filter(key => key === "GET /ft-api/v1/sandbox/status")).toHaveLength(2);
});

it("renders a genuine complete zero balance and zero P&L without an unavailable warning", async () => {
  mountReads(() => response({ ...validStatus, data: { ...validStatus.data, capital: 0 } }), () => response(validPolicy));
  expect(await screen.findByText("₹0.00")).toBeVisible();
  expect(screen.getByLabelText("P&L: +₹0.00")).toBeVisible();
  expect(screen.queryByText(/Sandbox balance and P&L unavailable/)).not.toBeInTheDocument();
  expect(await screen.findByLabelText("Starting capital")).toHaveValue(policy.starting_capital);
  expect(requests).toEqual(["GET /ft-api/v1/sandbox/status", "GET /ft-api/v1/sandbox/config"]);
});

it.each(["error", undefined])("refuses policy with non-success status %s even if its fields look valid", async status => {
  mountReads(() => response(validStatus), () => response({ ...validPolicy, status }));
  expect(await screen.findByText(/Practice policy unavailable/, {}, { timeout: 2500 })).toBeVisible();
  expect(screen.queryByLabelText("Starting capital")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Save Policy" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("P&L: +₹0.00")).toBeVisible();
  expect(requests.filter(key => key === "GET /ft-api/v1/sandbox/config")).toHaveLength(2);
  expect(requests.filter(key => key.startsWith("POST"))).toEqual([]);
});

it("does not announce a saved policy from a successful-HTTP error envelope", async () => {
  mountReads(() => response(validStatus), () => response(validPolicy), init => {
    expect(JSON.parse(String(init.body))).toEqual({ ...policy, equity_leverage: 4 });
    return response({ status: "error", data: { config: { ...policy, equity_leverage: 4 } } });
  });
  fireEvent.change(await screen.findByLabelText("Equity leverage"), { target: { value: "4" } });
  fireEvent.click(screen.getByRole("button", { name: "Save Policy" }));
  expect(await screen.findByRole("alert")).toBeVisible();
  expect(screen.queryByText("Practice policy saved.")).not.toBeInTheDocument();
  expect(requests.filter(key => key === "POST /ft-api/v1/sandbox/config")).toHaveLength(1);
});
