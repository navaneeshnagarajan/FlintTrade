/**
 * brokerOrdersApi unit tests — locks the wire contract of the gated broker
 * order-management client: URLs (incl. the /ft-api dev prefix and encoded
 * path ids), methods, query-string targeting, body shapes, the
 * {status, data} unwrap, and the honest error mapping (backend messages
 * verbatim + the 501 "Not available for this broker" detection).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Force DEV mode so getBase() returns "/ft-api". Stub before importing the
// module because Vite inlines `import.meta.env.DEV` at module-load time.
vi.stubEnv("DEV", true);

const storeState = vi.hoisted(() => ({
  mode: "live",
  apiKey: "test-api-key",
  token: "test-jwt",
  brokerState: {
    accounts: [] as Array<{
      account_id: string;
      broker: string;
      source?: "gateway" | "native";
      status?: string;
    }>,
    activeAccountId: null as string | null,
  },
}));

// buildHeaders reads these stores imperatively on every call.
vi.mock("@/stores/connectionStore", () => ({
  // openAlgoHydrated: true models a normally-loaded app; the hydration
  // fail-closed window is covered by brokerTargets/api tests.
  useConnectionStore: { getState: () => ({ apiKey: storeState.apiKey, openAlgoHydrated: true }) },
}));
vi.mock("@/stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: storeState.token }) },
}));
vi.mock("@/stores/modeStore", () => ({
  useModeStore: { getState: () => ({ mode: storeState.mode }) },
}));
vi.mock("@/stores/brokerStore", () => ({
  findBrokerAccountMatch: (
    accounts: Array<{ account_id: string; broker: string; source?: "gateway" | "native" }>,
    selector: string | null,
  ) => accounts.find((account) => mockBrokerAccountMatch(account, selector)),
  isBrokerAccountMatch: (
    account: { account_id: string; broker: string; source?: "gateway" | "native" },
    selector: string | null,
  ) => mockBrokerAccountMatch(account, selector),
  useBrokerStore: { getState: () => storeState.brokerState },
}));

import {
  BrokerOrdersApiError,
  brokerOrderKeys,
  cancelAllOrders,
  cancelConditionalTrigger,
  cancelForeverOrder,
  cancelSmartOrder,
  cancelSuperOrder,
  isUnsupportedForBroker,
  listConditionalTriggers,
  listForeverOrders,
  listSuperOrders,
  modifyConditionalTrigger,
  modifyForeverOrder,
  modifySuperOrder,
  placeConditionalTrigger,
  placeForeverOrder,
  placeMultiOrder,
} from "./brokerOrdersApi";

function mockBrokerAccountMatch(
  account: { account_id: string; broker: string; source?: "gateway" | "native" },
  selector: string | null,
) {
  if (!selector) return false;
  const key = [account.source ?? "gateway", account.broker, account.account_id]
    .map(encodeURIComponent)
    .join(":");
  return selector === key || selector === account.account_id;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function fetchMock(): ReturnType<typeof vi.fn> {
  return fetch as unknown as ReturnType<typeof vi.fn>;
}

function lastCall(): { url: string; init: RequestInit } {
  const calls = fetchMock().mock.calls;
  const [url, init] = calls[calls.length - 1] as [string, RequestInit];
  return { url, init };
}

function lastBody(): Record<string, unknown> {
  return JSON.parse(lastCall().init.body as string) as Record<string, unknown>;
}

beforeEach(() => {
  storeState.mode = "live";
  storeState.apiKey = "test-api-key";
  storeState.token = "test-jwt";
  storeState.brokerState = { accounts: [], activeAccountId: null };
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// Forever (GTT) orders
// ---------------------------------------------------------------------------

describe("forever orders", () => {
  it("lists with broker/account query params and unwraps data", async () => {
    fetchMock().mockResolvedValue(
      jsonResponse({ status: "success", data: [{ order_id: "G1", symbol: "RELIANCE" }] }),
    );
    const rows = await listForeverOrders({ broker: "dhan", account_id: "A1" });
    const { url, init } = lastCall();
    expect(url).toBe("/ft-api/api/v1/orders/forever?broker=dhan&account_id=A1");
    expect(init.method).toBe("GET");
    expect(init.headers).toStrictEqual({
      Authorization: "Bearer test-jwt",
      "X-API-Key": "test-api-key",
    });
    expect(rows).toStrictEqual([{ order_id: "G1", symbol: "RELIANCE" }]);
  });

  it("omits the query string for the default target and filters junk rows", async () => {
    fetchMock().mockResolvedValue(
      jsonResponse({ status: "success", data: [{ order_id: "G1" }, "garbage", null, 42] }),
    );
    const rows = await listForeverOrders();
    expect(lastCall().url).toBe("/ft-api/api/v1/orders/forever");
    expect(rows).toStrictEqual([{ order_id: "G1" }]);
  });

  it("defaults list requests to the active native account in live native-only mode", async () => {
    storeState.apiKey = "";
    storeState.brokerState = {
      accounts: [
        { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
      ],
      activeAccountId: "native:upstox:U1",
    };
    fetchMock().mockResolvedValue(jsonResponse({ status: "success", data: [] }));

    await listForeverOrders();

    expect(lastCall().url).toBe("/ft-api/api/v1/orders/forever?broker=upstox&account_id=U1");
  });

  it("places with variety gtt, the OCO trio, and auth headers", async () => {
    fetchMock().mockResolvedValue(jsonResponse({ status: "success", orderid: "G2", data: "G2" }));
    await placeForeverOrder({
      broker: "dhan",
      account_id: "A1",
      symbol: "RELIANCE",
      exchange: "NSE",
      action: "BUY",
      quantity: 10,
      price: 2900,
      trigger_price: 2895,
      entry_trigger_type: "BELOW",
      product: "CNC",
      pricetype: "LIMIT",
      validity: "DAY",
      price1: 3100,
      trigger_price1: 3105,
      quantity1: 10,
    });
    const { url, init } = lastCall();
    expect(url).toBe("/ft-api/api/v1/orders/forever");
    expect(init.method).toBe("POST");
    const headers = init.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers["Authorization"]).toBe("Bearer test-jwt");
    expect(headers["X-API-Key"]).toBe("test-api-key");
    expect(headers["X-FlintTrade-Mode"]).toBe("live");
    const body = lastBody();
    expect(body.variety).toBe("gtt");
    expect(body.symbol).toBe("RELIANCE");
    expect(body.trigger_price).toBe(2895);
    expect(body.entry_trigger_type).toBe("BELOW");
    expect(body.price1).toBe(3100);
    expect(body.trigger_price1).toBe(3105);
    expect(body.quantity1).toBe(10);
    expect(body.broker).toBe("dhan");
  });

  it("defaults place requests to the active native account in live native-only mode", async () => {
    storeState.apiKey = "";
    storeState.brokerState = {
      accounts: [
        { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
      ],
      activeAccountId: "native:upstox:U1",
    };
    fetchMock().mockResolvedValue(jsonResponse({ status: "success", orderid: "G2" }));

    await placeForeverOrder({
      symbol: "RELIANCE",
      exchange: "NSE",
      action: "BUY",
      quantity: 10,
    });

    expect(lastBody()).toMatchObject({ broker: "upstox", account_id: "U1" });
  });

  it("does not override an explicit broker target when a native account is active", async () => {
    storeState.apiKey = "";
    storeState.brokerState = {
      accounts: [
        { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
      ],
      activeAccountId: "native:upstox:U1",
    };
    fetchMock().mockResolvedValue(jsonResponse({ status: "success", orderid: "G2" }));

    await placeForeverOrder({
      broker: "dhan",
      account_id: "D1",
      symbol: "RELIANCE",
      exchange: "NSE",
      action: "BUY",
      quantity: 10,
    });

    expect(lastBody()).toMatchObject({ broker: "dhan", account_id: "D1" });
  });

  it("modifies via PUT with an encoded order id and a changes body", async () => {
    fetchMock().mockResolvedValue(jsonResponse({ status: "success", orderid: "a/b" }));
    await modifyForeverOrder({
      order_id: "a/b",
      changes: { price: 2900 },
      broker: "dhan",
      account_id: "A1",
    });
    const { url, init } = lastCall();
    expect(url).toBe("/ft-api/api/v1/orders/forever/a%2Fb");
    expect(init.method).toBe("PUT");
    expect(new Headers(init.headers).get("X-FlintTrade-Mode")).toBe("live");
    expect(lastBody()).toStrictEqual({
      changes: { price: 2900 },
      broker: "dhan",
      account_id: "A1",
    });
  });

  it("cancels via DELETE with the target in the query string", async () => {
    fetchMock().mockResolvedValue(jsonResponse({ status: "success", orderid: "G1" }));
    await cancelForeverOrder({ order_id: "G1", broker: "dhan", account_id: "A1" });
    const { url, init } = lastCall();
    expect(url).toBe("/ft-api/api/v1/orders/forever/G1?broker=dhan&account_id=A1");
    expect(new Headers(init.headers).get("X-FlintTrade-Mode")).toBe("live");
    expect(init.method).toBe("DELETE");
    expect(init.body).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// Super orders
// ---------------------------------------------------------------------------

describe("super orders", () => {
  it("lists from /orders/super", async () => {
    fetchMock().mockResolvedValue(jsonResponse({ status: "success", data: [] }));
    await listSuperOrders({ broker: "dhan" });
    expect(lastCall().url).toBe("/ft-api/api/v1/orders/super?broker=dhan");
  });

  it("modifies a leg via changes.leg_name", async () => {
    fetchMock().mockResolvedValue(jsonResponse({ status: "success", orderid: "S1" }));
    await modifySuperOrder({
      order_id: "S1",
      changes: { leg_name: "TARGET_LEG", price: 105 },
      broker: "dhan",
    });
    const { url, init } = lastCall();
    expect(url).toBe("/ft-api/api/v1/orders/super/S1");
    expect(init.method).toBe("PUT");
    expect(lastBody().changes).toStrictEqual({ leg_name: "TARGET_LEG", price: 105 });
  });

  it("defaults leg modifies to the active native account in live native-only mode", async () => {
    storeState.apiKey = "";
    storeState.brokerState = {
      accounts: [
        { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
      ],
      activeAccountId: "native:upstox:U1",
    };
    fetchMock().mockResolvedValue(jsonResponse({ status: "success", orderid: "S1" }));

    await modifySuperOrder({
      order_id: "S1",
      changes: { leg_name: "TARGET_LEG", price: 105 },
    });

    expect(lastBody()).toMatchObject({
      changes: { leg_name: "TARGET_LEG", price: 105 },
      broker: "upstox",
      account_id: "U1",
    });
  });

  it("cancels one leg via the ?leg= query parameter", async () => {
    fetchMock().mockResolvedValue(jsonResponse({ status: "success", orderid: "S1" }));
    await cancelSuperOrder({ order_id: "S1", leg: "STOP_LOSS_LEG", broker: "dhan" });
    const { url, init } = lastCall();
    expect(url).toBe("/ft-api/api/v1/orders/super/S1?broker=dhan&leg=STOP_LOSS_LEG");
    expect(init.method).toBe("DELETE");
  });
});

// ---------------------------------------------------------------------------
// Conditional triggers
// ---------------------------------------------------------------------------

describe("conditional triggers", () => {
  const condition = {
    comparisonType: "PRICE_WITH_VALUE",
    exchangeSegment: "NSE_EQ",
    securityId: "12345",
    operator: "GREATER_THAN",
    comparingValue: 250,
    frequency: "ONCE",
  };
  const orders = [
    {
      symbol: "RELIANCE",
      exchange: "NSE" as const,
      action: "BUY" as const,
      quantity: 10,
      price: 250,
      pricetype: "LIMIT",
      product: "CNC",
    },
  ];

  it("lists from /orders/triggers", async () => {
    fetchMock().mockResolvedValue(jsonResponse({ status: "success", data: [] }));
    await listConditionalTriggers();
    expect(lastCall().url).toBe("/ft-api/api/v1/orders/triggers");
  });

  it("places with condition + orders in the body", async () => {
    fetchMock().mockResolvedValue(jsonResponse({ status: "success", data: { alertId: "AL1" } }));
    await placeConditionalTrigger({ condition, orders, broker: "dhan" });
    const { url, init } = lastCall();
    expect(url).toBe("/ft-api/api/v1/orders/triggers");
    expect(init.method).toBe("POST");
    const body = lastBody();
    expect(body.condition).toStrictEqual(condition);
    expect(body.orders).toStrictEqual(orders);
    expect(body.broker).toBe("dhan");
  });

  it("modifies via PUT to the alert id, keeping alert_id out of the body", async () => {
    fetchMock().mockResolvedValue(jsonResponse({ status: "success", orderid: "AL1" }));
    await modifyConditionalTrigger({ alert_id: "AL1", condition, orders });
    const { url, init } = lastCall();
    expect(url).toBe("/ft-api/api/v1/orders/triggers/AL1");
    expect(init.method).toBe("PUT");
    const body = lastBody();
    expect(body.alert_id).toBeUndefined();
    expect(body.condition).toStrictEqual(condition);
  });

  it("cancels via DELETE to the alert id", async () => {
    fetchMock().mockResolvedValue(jsonResponse({ status: "success", orderid: "AL1" }));
    await cancelConditionalTrigger({ alert_id: "AL1", broker: "dhan" });
    const { url, init } = lastCall();
    expect(url).toBe("/ft-api/api/v1/orders/triggers/AL1?broker=dhan");
    expect(init.method).toBe("DELETE");
  });
});

// ---------------------------------------------------------------------------
// Batch + sweep verbs
// ---------------------------------------------------------------------------

describe("multi / cancel-all / smart cancel", () => {
  it("places a multi-order batch", async () => {
    fetchMock().mockResolvedValue(jsonResponse({ status: "success", data: [] }));
    await placeMultiOrder({
      orders: [
        { symbol: "TCS", exchange: "NSE", action: "BUY", quantity: 5, pricetype: "MARKET" },
      ],
      broker: "upstox",
    });
    const { url, init } = lastCall();
    expect(url).toBe("/ft-api/api/v1/orders/multi");
    expect(init.method).toBe("POST");
    expect((lastBody().orders as unknown[]).length).toBe(1);
  });

  it("cancel-all posts broker + optional narrowing fields", async () => {
    fetchMock().mockResolvedValue(jsonResponse({ status: "success", data: {} }));
    await cancelAllOrders({ broker: "dhan", segment: "EQUITY" });
    const { url } = lastCall();
    expect(url).toBe("/ft-api/api/v1/orders/cancel-all");
    expect(lastBody()).toStrictEqual({ broker: "dhan", segment: "EQUITY" });
  });

  it("smart-order cancel passes segment in the query", async () => {
    fetchMock().mockResolvedValue(jsonResponse({ status: "success", orderid: "SM1" }));
    await cancelSmartOrder({ order_id: "SM1", segment: "DERIVATIVE", broker: "indmoney" });
    const { url, init } = lastCall();
    expect(url).toBe("/ft-api/api/v1/orders/smart/SM1?broker=indmoney&segment=DERIVATIVE");
    expect(init.method).toBe("DELETE");
  });
});

// ---------------------------------------------------------------------------
// Error mapping — honest surfaces only
// ---------------------------------------------------------------------------

describe("error mapping", () => {
  it("throws the backend's message verbatim with the HTTP status", async () => {
    fetchMock().mockResolvedValue(
      jsonResponse({ status: "error", message: "Live mode not unlocked — verify PIN first" }, 403),
    );
    const failure = listForeverOrders();
    await expect(failure).rejects.toThrow("Live mode not unlocked — verify PIN first");
    try {
      await listForeverOrders();
    } catch (error) {
      expect(error).toBeInstanceOf(BrokerOrdersApiError);
      expect((error as BrokerOrdersApiError).status).toBe(403);
      expect(isUnsupportedForBroker(error)).toBe(false);
    }
  });

  it("maps a 501 to isUnsupportedForBroker", async () => {
    fetchMock().mockResolvedValue(
      jsonResponse(
        {
          status: "error",
          message: "broker adapter 'openalgo' does not support the 'super_orders' listing",
        },
        501,
      ),
    );
    try {
      await listSuperOrders();
      expect.unreachable("listSuperOrders should have thrown");
    } catch (error) {
      expect(isUnsupportedForBroker(error)).toBe(true);
    }
  });

  it("throws on an HTTP-200 body that carries status error", async () => {
    fetchMock().mockResolvedValue(
      jsonResponse({ status: "error", message: "Trigger validation failed: bad condition" }),
    );
    await expect(placeConditionalTrigger({ condition: { a: 1 }, orders: [] })).rejects.toThrow(
      "Trigger validation failed: bad condition",
    );
  });

  it("reports an unreachable backend without fabricating a response", async () => {
    fetchMock().mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(listForeverOrders()).rejects.toThrow(
      "Cannot reach the FlintTrade backend — check that it is running.",
    );
  });
});

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

describe("brokerOrderKeys", () => {
  it("defaults to the openalgo/default selector and stays namespaced", () => {
    expect(brokerOrderKeys.forever.list()).toStrictEqual([
      "brokerOrders",
      "forever",
      "openalgo",
      "default",
    ]);
    expect(brokerOrderKeys.superOrders.list({ broker: "dhan", account_id: "A1" })).toStrictEqual([
      "brokerOrders",
      "super",
      "dhan",
      "A1",
    ]);
    expect(brokerOrderKeys.triggers.all).toStrictEqual(["brokerOrders", "triggers"]);
  });

  it("keys omitted targets by the active native account in live native-only mode", () => {
    storeState.apiKey = "";
    storeState.brokerState = {
      accounts: [
        { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
      ],
      activeAccountId: "native:upstox:U1",
    };

    expect(brokerOrderKeys.forever.list()).toStrictEqual([
      "brokerOrders",
      "forever",
      "upstox",
      "U1",
    ]);
    expect(brokerOrderKeys.superOrders.list()).toStrictEqual([
      "brokerOrders",
      "super",
      "upstox",
      "U1",
    ]);
    expect(brokerOrderKeys.triggers.list()).toStrictEqual([
      "brokerOrders",
      "triggers",
      "upstox",
      "U1",
    ]);
  });
});
