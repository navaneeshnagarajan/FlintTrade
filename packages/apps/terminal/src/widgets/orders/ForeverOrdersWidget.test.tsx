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
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
  window.HTMLElement.prototype.hasPointerCapture = vi.fn();
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
  useModeStore: Object.assign(
    (selector?: (s: { mode: string }) => unknown) =>
      typeof selector === "function" ? selector({ mode: mockMode }) : { mode: mockMode },
    { getState: () => ({ mode: mockMode }) },
  ),
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
  order_flag: "SINGLE",
  pricetype: "LIMIT",
  validity: "DAY",
  disclosed_quantity: 0,
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
  mockBrokerState.accounts = [
    {
      account_id: "D1",
      broker: "dhan",
      label: "Dhan Live",
      source: "native",
      status: "connected",
    },
  ];
  mockBrokerState.activeAccountId = "native:dhan:D1";
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

  it("fails closed when no supported native GTT account is connected", () => {
    mockBrokerState.accounts = [
      {
        account_id: "G1",
        broker: "groww",
        label: "Groww",
        source: "native",
        status: "connected",
      },
    ];
    mockBrokerState.activeAccountId = "native:groww:G1";

    renderWidget();

    expect(screen.getByText(/connect a writable Dhan or Upstox account/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /place gtt/i })).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("lists real resting forever orders in Live mode", async () => {
    renderWidget();
    await waitFor(() => expect(screen.getByText("RELIANCE")).toBeInTheDocument());
    expect(screen.getByText("ACTIVE")).toBeInTheDocument();
    const [url] = callsByMethod("GET")[0];
    expect(url).toContain("/api/v1/orders/forever");
    expect(url).toContain("broker=dhan");
    expect(url).toContain("account_id=D1");
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
    expect(body.entry_trigger_type).toBeUndefined();
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

  it("places Upstox GTT ENTRY, STOPLOSS, and TARGET rules without Dhan fields", async () => {
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

    fireEvent.change(screen.getByLabelText("GTT symbol"), { target: { value: "reliance" } });
    fireEvent.change(screen.getByLabelText("GTT quantity"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("GTT trigger price"), { target: { value: "2895" } });
    fireEvent.click(screen.getByRole("switch", { name: "Stop-loss rule" }));
    fireEvent.click(screen.getByRole("switch", { name: "Target rule" }));
    fireEvent.change(screen.getByLabelText("Stop-loss trigger price"), { target: { value: "2800" } });
    fireEvent.change(screen.getByLabelText("Target trigger price"), { target: { value: "3100" } });
    fireEvent.click(screen.getByRole("button", { name: /place gtt/i }));

    await waitFor(() => expect(callsByMethod("POST").length).toBe(1));
    const [, init] = callsByMethod("POST")[0];
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body).toMatchObject({
      broker: "upstox",
      account_id: "U1",
      trigger_price: 2895,
      entry_trigger_type: "ABOVE",
      stop_loss_price: 2800,
      stop_loss_trigger_type: "IMMEDIATE",
      target_price: 3100,
      target_trigger_type: "IMMEDIATE",
    });
    expect(body.price1).toBeUndefined();
    expect(body.trigger_price1).toBeUndefined();
    expect(body.quantity1).toBeUndefined();
  });

  it("cancels a row via the gated DELETE", async () => {
    renderWidget();
    await waitFor(() => expect(screen.getByText("RELIANCE")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /^cancel$/i }));

    await waitFor(() => expect(callsByMethod("DELETE").length).toBe(1));
    const [url] = callsByMethod("DELETE")[0];
    expect(url).toContain("/api/v1/orders/forever/GTT-1");
    expect(url).toContain("broker=dhan");
    expect(url).toContain("account_id=D1");
  });

  it("modifies a Dhan row with the complete selected-leg replacement", async () => {
    renderWidget();
    await waitFor(() => expect(screen.getByText("RELIANCE")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /modify/i }));
    fireEvent.change(screen.getByLabelText("New trigger price"), { target: { value: "2950" } });
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));

    await waitFor(() => expect(callsByMethod("PUT").length).toBe(1));
    const [url, init] = callsByMethod("PUT")[0];
    expect(url).toContain("/api/v1/orders/forever/GTT-1");
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.changes).toStrictEqual({
      order_flag: "SINGLE",
      leg_name: "TARGET_LEG",
      pricetype: "LIMIT",
      validity: "DAY",
      quantity: 10,
      price: 2900,
      trigger_price: 2950,
      disclosed_quantity: 0,
    });
  });

  it.each([
    ["STOP_LOSS", "SL"],
    ["STOP_LOSS_MARKET", "SLM"],
  ])("offers Dhan's %s forever-modify order type", async (label, expectedValue) => {
    renderWidget();
    await waitFor(() => expect(screen.getByText("RELIANCE")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /modify/i }));
    fireEvent.click(screen.getByLabelText("New price type"));
    fireEvent.click(await screen.findByRole("option", { name: label }));
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));

    await waitFor(() => expect(callsByMethod("PUT").length).toBe(1));
    const [, init] = callsByMethod("PUT")[0];
    const body = JSON.parse(init.body as string) as { changes: Record<string, unknown> };
    expect(body.changes.pricetype).toBe(expectedValue);
  });

  it("prefills SL for a resting STOP_LOSS forever order — never silently LIMIT", async () => {
    // Regression: dhanModifyPriceType("SL") used to fall through to "LIMIT",
    // so an innocent trigger-price edit rewrote the resting leg's order type
    // at the broker under the complete-replacement modify contract.
    listRows = [{ ...LIST_ROW, pricetype: "SL" }];
    renderWidget();
    await waitFor(() => expect(screen.getByText("RELIANCE")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /modify/i }));
    fireEvent.change(screen.getByLabelText("New trigger price"), { target: { value: "2950" } });
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));

    await waitFor(() => expect(callsByMethod("PUT").length).toBe(1));
    const [, init] = callsByMethod("PUT")[0];
    const body = JSON.parse(init.body as string) as { changes: Record<string, unknown> };
    expect(body.changes.pricetype).toBe("SL");
  });

  it("fails closed on an unrecognised broker price type — Apply stays disabled", async () => {
    listRows = [{ ...LIST_ROW, pricetype: "MYSTERY_TYPE" }];
    renderWidget();
    await waitFor(() => expect(screen.getByText("RELIANCE")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /modify/i }));
    fireEvent.change(screen.getByLabelText("New trigger price"), { target: { value: "2950" } });
    const apply = screen.getByRole("button", { name: /apply/i });
    expect(apply).toBeDisabled();
    // Choosing a type deliberately re-enables Apply.
    fireEvent.click(screen.getByLabelText("New price type"));
    fireEvent.click(await screen.findByRole("option", { name: "STOP_LOSS" }));
    expect(screen.getByRole("button", { name: /apply/i })).toBeEnabled();
  });

  it("modifies the selected Dhan OCO stop-loss leg instead of the first leg", async () => {
    listRows = [
      {
        ...LIST_ROW,
        order_flag: "OCO",
        quantity1: 10,
        price1: 2750,
        trigger_price1: 2755,
      },
    ];
    renderWidget();
    await waitFor(() => expect(screen.getByText("RELIANCE")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /modify/i }));
    fireEvent.click(screen.getByLabelText("Forever order leg"));
    fireEvent.click(await screen.findByRole("option", { name: "Stop-loss leg" }));
    fireEvent.change(screen.getByLabelText("New trigger price"), { target: { value: "2760" } });
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));

    await waitFor(() => expect(callsByMethod("PUT").length).toBe(1));
    const [, init] = callsByMethod("PUT")[0];
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.changes).toStrictEqual({
      order_flag: "OCO",
      leg_name: "STOP_LOSS_LEG",
      pricetype: "LIMIT",
      validity: "DAY",
      quantity: 10,
      price: 2750,
      trigger_price: 2760,
      disclosed_quantity: 0,
    });
  });

  it("modifies an Upstox row by resending its complete rule set", async () => {
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
    listRows = [
      {
        gtt_order_id: "GTT-CU100",
        symbol: "RELIANCE",
        quantity: "2",
        rules: [
          { strategy: "ENTRY", status: "SCHEDULED", trigger_type: "BELOW", trigger_price: "2895" },
          {
            strategy: "STOPLOSS",
            status: "SCHEDULED",
            trigger_type: "IMMEDIATE",
            trigger_price: "2800",
            trailing_gap: "0.5",
          },
          { strategy: "TARGET", status: "SCHEDULED", trigger_type: "IMMEDIATE", trigger_price: "3100" },
        ],
      },
    ];
    renderWidget();
    await waitFor(() => expect(screen.getByText("RELIANCE")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /modify/i }));
    fireEvent.change(screen.getByLabelText("New target trigger price"), { target: { value: "3150" } });
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));

    await waitFor(() => expect(callsByMethod("PUT").length).toBe(1));
    const [url, init] = callsByMethod("PUT")[0];
    expect(url).toContain("/api/v1/orders/forever/GTT-CU100");
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.changes).toStrictEqual({
      type: "MULTIPLE",
      quantity: 2,
      trigger_price: 2895,
      entry_trigger_type: "BELOW",
      stop_loss_price: 2800,
      stop_loss_trailing_gap: 0.5,
      target_price: 3150,
      stop_loss_trigger_type: "IMMEDIATE",
      target_trigger_type: "IMMEDIATE",
    });
  });

  it("keeps an OPEN Upstox GTT quantity fixed and pins ENTRY to IMMEDIATE", async () => {
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
    listRows = [
      {
        gtt_order_id: "GTT-CU101",
        symbol: "RELIANCE",
        quantity: "2",
        status: "OPEN",
        rules: [
          { strategy: "ENTRY", status: "OPEN", trigger_type: "ABOVE", trigger_price: "2895" },
          { strategy: "TARGET", status: "SCHEDULED", trigger_type: "IMMEDIATE", trigger_price: "3100" },
        ],
      },
    ];
    renderWidget();
    await waitFor(() => expect(screen.getByText("RELIANCE")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /modify/i }));

    expect(screen.getByLabelText("New quantity")).toBeDisabled();
    expect(screen.getByLabelText("New entry trigger type")).toBeDisabled();
    expect(screen.getByLabelText("New entry trigger type")).toHaveTextContent("IMMEDIATE");
    fireEvent.change(screen.getByLabelText("New target trigger price"), { target: { value: "3150" } });
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));

    await waitFor(() => expect(callsByMethod("PUT").length).toBe(1));
    const [, init] = callsByMethod("PUT")[0];
    const body = JSON.parse(init.body as string) as { changes: Record<string, unknown> };
    expect(body.changes.quantity).toBe(2);
    expect(body.changes.entry_trigger_type).toBe("IMMEDIATE");
    expect(body.changes.stop_loss_trailing_gap).toBe(0);
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
