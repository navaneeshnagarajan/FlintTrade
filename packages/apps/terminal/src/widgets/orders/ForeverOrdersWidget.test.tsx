/**
 * ForeverOrdersWidget.test — live-mode gating, real list rendering, gated
 * place/modify/cancel wire calls, OCO toggle, and the 501 broker mapping.
 *
 * The global fetch is stubbed (no module mocks for the api), so these tests
 * exercise the REAL brokerOrdersApi client end to end through the hooks.
 */

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Radix internals (Switch thumb sizing) reference ResizeObserver.
beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

let mockMode = "live";
const mockConnectionState = vi.hoisted(() => ({
  apiKey: "test-openalgo-key",
  // openAlgoHydrated: true models a normally-loaded app; the hydration
  // fail-closed window is covered by brokerTargets/api tests.
  openAlgoHydrated: true,
}));
const mockBrokerState = vi.hoisted(() => ({
  accounts: [] as Array<{
    account_id: string;
    broker: string;
    label: string;
    source?: string;
    status?: string;
  }>,
  activeAccountId: null as string | null,
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector?: (s: { mode: string }) => unknown) =>
    typeof selector === "function" ? selector({ mode: mockMode }) : { mode: mockMode },
}));

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: Object.assign(
    (selector?: (s: { apiKey: string }) => unknown) =>
      typeof selector === "function" ? selector(mockConnectionState) : mockConnectionState,
    { getState: () => mockConnectionState },
  ),
}));

vi.mock("@/stores/brokerStore", () => ({
  findBrokerAccountMatch: (
    accounts: Array<{ account_id: string; broker: string; source?: string }>,
    selector: string | null,
  ) => accounts.find((account) => mockBrokerAccountMatch(account, selector)),
  isBrokerAccountMatch: (
    account: { account_id: string; broker: string; source?: string },
    selector: string | null,
  ) => mockBrokerAccountMatch(account, selector),
  useBrokerStore: Object.assign(
    (selector?: (s: typeof mockBrokerState) => unknown) =>
      typeof selector === "function" ? selector(mockBrokerState) : mockBrokerState,
    { getState: () => mockBrokerState },
  ),
}));

import ForeverOrdersWidget from "./ForeverOrdersWidget";

function mockBrokerAccountMatch(
  account: { account_id: string; broker: string; source?: string },
  selector: string | null,
) {
  if (!selector) return false;
  const key = [
    account.source ?? "gateway",
    account.broker,
    account.account_id,
  ].map(encodeURIComponent).join(":");
  return key === selector || account.account_id === selector;
}

const LIST_ROW = {
  order_id: "GTT-1",
  symbol: "RELIANCE",
  action: "BUY",
  quantity: 10,
  trigger_price: 2895,
  price: 2900,
  status: "ACTIVE",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

let listRows: unknown[] = [LIST_ROW];
let listStatus = 200;
let listMessage = "";

const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
  const method = init?.method ?? "GET";
  if (method === "GET") {
    if (listStatus !== 200) {
      return Promise.resolve(jsonResponse({ status: "error", message: listMessage }, listStatus));
    }
    return Promise.resolve(jsonResponse({ status: "success", data: listRows }));
  }
  return Promise.resolve(jsonResponse({ status: "success", orderid: "GTT-9", data: "GTT-9" }));
});

function callsByMethod(method: string): [string, RequestInit][] {
  return fetchMock.mock.calls.filter(
    ([, init]) => ((init as RequestInit | undefined)?.method ?? "GET") === method,
  ) as [string, RequestInit][];
}

function renderWidget() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ForeverOrdersWidget />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockMode = "live";
  mockConnectionState.apiKey = "test-openalgo-key";
  mockBrokerState.accounts = [];
  mockBrokerState.activeAccountId = null;
  listRows = [LIST_ROW];
  listStatus = 200;
  listMessage = "";
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ForeverOrdersWidget", () => {
  it("renders the header", () => {
    renderWidget();
    expect(screen.getByText("Forever (GTT) Orders")).toBeInTheDocument();
  });

  it("outside Live mode: honest notice, no fetch, submit disabled", () => {
    mockMode = "practice";
    renderWidget();
    expect(screen.getByText(/live-broker constructs/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /place gtt/i })).toBeDisabled();
  });

  it("lists real resting forever orders in Live mode", async () => {
    renderWidget();
    await waitFor(() => expect(screen.getByText("RELIANCE")).toBeInTheDocument());
    expect(screen.getByText("ACTIVE")).toBeInTheDocument();
    const [url] = callsByMethod("GET")[0];
    expect(url).toContain("/api/v1/orders/forever");
    expect(url).toContain("broker=openalgo");
  });

  it("defaults to the active native account in live native-only mode", async () => {
    mockConnectionState.apiKey = "";
    mockBrokerState.accounts = [
      {
        account_id: "U1",
        broker: "upstox",
        label: "Upstox Live",
        source: "native",
        status: "connected",
      },
    ];
    mockBrokerState.activeAccountId = "native:upstox:U1";

    renderWidget();

    await waitFor(() => expect(screen.getByText("RELIANCE")).toBeInTheDocument());
    const [url] = callsByMethod("GET")[0];
    expect(url).toContain("/api/v1/orders/forever");
    expect(url).toContain("broker=upstox");
    expect(url).toContain("account_id=U1");
  });

  it("places a GTT order through the gated POST with typed fields", async () => {
    renderWidget();
    fireEvent.change(screen.getByLabelText("GTT symbol"), { target: { value: "reliance" } });
    fireEvent.change(screen.getByLabelText("GTT quantity"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("GTT trigger price"), { target: { value: "2895" } });
    fireEvent.change(screen.getByLabelText("GTT limit price"), { target: { value: "2900" } });
    fireEvent.click(screen.getByRole("button", { name: /place gtt/i }));

    await waitFor(() => expect(callsByMethod("POST").length).toBe(1));
    const [url, init] = callsByMethod("POST")[0];
    expect(url).toContain("/api/v1/orders/forever");
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.variety).toBe("gtt");
    expect(body.symbol).toBe("RELIANCE");
    expect(body.action).toBe("BUY");
    expect(body.quantity).toBe(10);
    expect(body.trigger_price).toBe(2895);
    expect(body.entry_trigger_type).toBe("ABOVE");
    expect(body.price).toBe(2900);
    expect(body.product).toBe("CNC");
    expect(body.pricetype).toBe("LIMIT");
    expect(body.validity).toBe("DAY");
    await waitFor(() =>
      expect(screen.getByText(/forever order accepted/i)).toBeInTheDocument(),
    );
  });

  it("the OCO toggle reveals the second leg and sends the trio", async () => {
    renderWidget();
    expect(screen.queryByLabelText("OCO trigger price")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: "OCO second leg" }));

    fireEvent.change(screen.getByLabelText("GTT symbol"), { target: { value: "TCS" } });
    fireEvent.change(screen.getByLabelText("GTT quantity"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("GTT trigger price"), { target: { value: "3000" } });
    fireEvent.change(screen.getByLabelText("GTT limit price"), { target: { value: "3005" } });
    fireEvent.change(screen.getByLabelText("OCO trigger price"), { target: { value: "3200" } });
    fireEvent.change(screen.getByLabelText("OCO price"), { target: { value: "3195" } });
    fireEvent.change(screen.getByLabelText("OCO quantity"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: /place gtt/i }));

    await waitFor(() => expect(callsByMethod("POST").length).toBe(1));
    const [, init] = callsByMethod("POST")[0];
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.trigger_price1).toBe(3200);
    expect(body.price1).toBe(3195);
    expect(body.quantity1).toBe(5);
  });

  it("cancels a row via the gated DELETE", async () => {
    renderWidget();
    await waitFor(() => expect(screen.getByText("RELIANCE")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /^cancel$/i }));

    await waitFor(() => expect(callsByMethod("DELETE").length).toBe(1));
    const [url] = callsByMethod("DELETE")[0];
    expect(url).toContain("/api/v1/orders/forever/GTT-1");
    expect(url).toContain("broker=openalgo");
  });

  it("modifies a row via the gated PUT with a changes object", async () => {
    renderWidget();
    await waitFor(() => expect(screen.getByText("RELIANCE")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /modify/i }));
    fireEvent.change(screen.getByLabelText("New trigger price"), { target: { value: "2950" } });
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));

    await waitFor(() => expect(callsByMethod("PUT").length).toBe(1));
    const [url, init] = callsByMethod("PUT")[0];
    expect(url).toContain("/api/v1/orders/forever/GTT-1");
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.changes).toStrictEqual({ trigger_price: 2950 });
  });

  it("maps the 501 unsupported-broker refusal honestly", async () => {
    listStatus = 501;
    listMessage = "broker adapter 'openalgo' does not support the 'forever_orders' listing";
    renderWidget();
    await waitFor(() =>
      expect(screen.getByText("Not available for this broker.")).toBeInTheDocument(),
    );
  });

  it("surfaces other backend refusals verbatim", async () => {
    listStatus = 403;
    listMessage =
      "This endpoint serves live mode only — forever (GTT), super orders, conditional triggers, and position writes are live-broker constructs. Switch to Live mode first.";
    renderWidget();
    await waitFor(() =>
      expect(screen.getByText(/serves live mode only/i)).toBeInTheDocument(),
    );
  });
});
