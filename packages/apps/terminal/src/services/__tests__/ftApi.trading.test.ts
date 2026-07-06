import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const storeState = vi.hoisted(() => ({
  mode: "live",
  apiKey: "",
  token: "",
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

vi.mock("@/stores/modeStore", () => ({
  useModeStore: {
    getState: () => ({ mode: storeState.mode }),
  },
}));

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: {
    getState: () => ({ apiKey: storeState.apiKey }),
  },
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: {
    getState: () => ({ token: storeState.token }),
  },
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
  useBrokerStore: {
    getState: () => storeState.brokerState,
  },
}));

import { startSmartRoute, type SmartRouteJob, type SmartRouteParams } from "../ftApi.trading";

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

const BASE_PARAMS: SmartRouteParams = {
  symbol: "RELIANCE",
  exchange: "NSE",
  action: "BUY",
  quantity: 10,
  urgency: "high",
};

const SMART_ROUTE_JOB: SmartRouteJob = {
  job_id: "job-1",
  created_at: "2026-07-05T00:00:00Z",
  status: "running",
  cancel_requested: false,
  error: "",
  symbol: "RELIANCE",
  exchange: "NSE",
  action: "BUY",
  urgency: "high",
  total_quantity: 10,
  filled_quantity: 0,
  average_slippage_bps: 0,
  completed: false,
  child_orders: [],
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function requestBody(fetchMock: ReturnType<typeof vi.fn>): Record<string, unknown> {
  const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  return JSON.parse(String(init.body)) as Record<string, unknown>;
}

describe("startSmartRoute", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    storeState.mode = "live";
    storeState.apiKey = "";
    storeState.token = "";
    storeState.brokerState = { accounts: [], activeAccountId: null };
    fetchMock = vi.fn().mockResolvedValue(jsonResponse({ status: "success", data: SMART_ROUTE_JOB }));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("adds the active native account target for live native-only smart routes", async () => {
    storeState.brokerState = {
      accounts: [
        { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
      ],
      activeAccountId: "native:upstox:U1",
    };

    await startSmartRoute(BASE_PARAMS);

    expect(requestBody(fetchMock)).toMatchObject({
      symbol: "RELIANCE",
      broker: "upstox",
      account_id: "U1",
    });
  });

  it("does not override an explicit smart-route broker target", async () => {
    storeState.brokerState = {
      accounts: [
        { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
      ],
      activeAccountId: "native:upstox:U1",
    };

    await startSmartRoute({ ...BASE_PARAMS, broker: "dhan", account_id: "D1" });

    expect(requestBody(fetchMock)).toMatchObject({ broker: "dhan", account_id: "D1" });
  });

  it("keeps OpenAlgo primary when an OpenAlgo API key is configured", async () => {
    storeState.apiKey = "openalgo-key";
    storeState.brokerState = {
      accounts: [
        { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
      ],
      activeAccountId: "native:upstox:U1",
    };

    await startSmartRoute(BASE_PARAMS);

    expect(requestBody(fetchMock)).not.toHaveProperty("broker");
    expect(requestBody(fetchMock)).not.toHaveProperty("account_id");
  });

  it("does not add a native target outside live mode", async () => {
    storeState.mode = "practice";
    storeState.brokerState = {
      accounts: [
        { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
      ],
      activeAccountId: "native:upstox:U1",
    };

    await startSmartRoute(BASE_PARAMS);

    expect(requestBody(fetchMock)).not.toHaveProperty("broker");
    expect(requestBody(fetchMock)).not.toHaveProperty("account_id");
  });

  it("fails closed instead of retargeting when the active native account is not yet connected", async () => {
    // Round-4 finding: the smart-route path must fail closed like postOrder — a
    // selected-but-unconfirmed native account (e.g. the post-reload window) must
    // not fall through to the bare path and be silently routed to
    // brokers.execution.default.
    storeState.brokerState = {
      accounts: [
        { account_id: "U1", broker: "upstox", source: "native", status: "disconnected" },
      ],
      activeAccountId: "native:upstox:U1",
    };

    await expect(startSmartRoute(BASE_PARAMS)).rejects.toThrow(/not available for live writes/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
