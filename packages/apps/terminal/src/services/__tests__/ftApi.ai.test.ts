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
  useModeStore: { getState: () => ({ mode: storeState.mode }) },
}));

vi.mock("@/stores/connectionStore", () => ({
  // openAlgoHydrated: true models a normally-loaded app; the hydration
  // fail-closed window is covered by brokerTargets/api tests.
  useConnectionStore: { getState: () => ({ apiKey: storeState.apiKey, openAlgoHydrated: true }) },
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: storeState.token }) },
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
  runTeamAnalysisStream,
  startAgent,
  type AgentSnapshot,
  type AgentStartParams,
  type TeamStreamFrame,
} from "../ftApi.ai";

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

const BASE_PARAMS: AgentStartParams = {
  symbols: ["RELIANCE"],
  exchange: "NSE",
  max_position_size: 1,
};

const AGENT_SNAPSHOT: AgentSnapshot = {
  enabled: true,
  running: true,
  started_at: "2026-07-05T00:00:00Z",
  params: {},
  actor_id: "autonomous-trader",
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

describe("startAgent", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    storeState.mode = "live";
    storeState.apiKey = "";
    storeState.token = "";
    storeState.brokerState = { accounts: [], activeAccountId: null };
    fetchMock = vi.fn().mockResolvedValue(jsonResponse({ status: "success", data: AGENT_SNAPSHOT }));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("adds the active native target for live native-only agent starts", async () => {
    storeState.brokerState = {
      accounts: [
        { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
      ],
      activeAccountId: "native:upstox:U1",
    };

    await startAgent(BASE_PARAMS);

    expect(requestBody(fetchMock)).toMatchObject({
      symbols: ["RELIANCE"],
      broker: "upstox",
      account_id: "U1",
    });
  });

  it("does not override an explicit agent target", async () => {
    storeState.brokerState = {
      accounts: [
        { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
      ],
      activeAccountId: "native:upstox:U1",
    };

    await startAgent({ ...BASE_PARAMS, broker: "dhan", account_id: "D1" });

    expect(requestBody(fetchMock)).toMatchObject({ broker: "dhan", account_id: "D1" });
  });

  it("keeps OpenAlgo primary when a bridge API key is configured", async () => {
    storeState.apiKey = "openalgo-key";
    storeState.brokerState = {
      accounts: [
        { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
      ],
      activeAccountId: "native:upstox:U1",
    };

    await startAgent(BASE_PARAMS);

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

    await startAgent(BASE_PARAMS);

    expect(requestBody(fetchMock)).not.toHaveProperty("broker");
    expect(requestBody(fetchMock)).not.toHaveProperty("account_id");
  });

  it("fails closed rather than starting an autonomous agent on a defaulted target", async () => {
    // Round-5 (HIGH): AgentPanel passes no explicit target and has no selector,
    // so an active native account that isn't confirmed connected must fail closed
    // — never bind an autonomous session to brokers.execution.default. The throw
    // is synchronous (argument position); TanStack's mutationFn routes it to
    // onError, exactly like startSmartRoute.
    storeState.brokerState = {
      accounts: [
        { account_id: "U1", broker: "upstox", source: "native", status: "disconnected" },
      ],
      activeAccountId: "native:upstox:U1",
    };

    expect(() => startAgent(BASE_PARAMS)).toThrow(/not available for live writes/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("runTeamAnalysisStream", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    storeState.apiKey = "openalgo-key";
    storeState.token = "jwt-token";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the selected mode and preset and yields typed SSE frames", async () => {
    const body = [
      'data: {"type":"event","event":{"task_id":"technical","agent_role":"technical","event_type":"started","data":{},"timestamp":"2026-07-10T00:00:00Z"}}\n\n',
      'data: {"type":"result","data":{"analysis":{"symbol":"NIFTY","exchange":"NSE_INDEX","agent_analyses":[],"consensus_signal":"HOLD","consensus_confidence":0,"consensus_reasoning":"","timestamp":"","errors":[],"mode":"dag","preset":"derivatives_desk","details":{}},"recommendation":{"symbol":"NIFTY","exchange":"NSE_INDEX","action":"HOLD","confidence":0,"reasoning":"","agent_count":0,"bullish_count":0,"bearish_count":0,"neutral_count":0,"timestamp":""}}}\n\n',
      'data: {"type":"done"}\n\n',
    ].join("");
    fetchMock = vi.fn().mockResolvedValue(
      new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const frames: TeamStreamFrame[] = [];
    for await (const frame of runTeamAnalysisStream("NIFTY", "NSE_INDEX", undefined, {
      mode: "dag",
      preset: "derivatives_desk",
      max_concurrent: 2,
    })) {
      frames.push(frame);
    }

    expect(frames.map((frame) => frame.type)).toEqual(["event", "result", "done"]);
    expect(frames[0]).toMatchObject({ type: "event", event: { event_type: "started" } });
    expect(frames[1]).toMatchObject({
      type: "result",
      data: { analysis: { mode: "dag", preset: "derivatives_desk" } },
    });
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/ai\/team\/analyse\/stream$/);
    expect(JSON.parse(String(init.body))).toEqual({
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      mode: "dag",
      preset: "derivatives_desk",
      max_concurrent: 2,
    });
    expect(init.headers).toMatchObject({ Authorization: "Bearer jwt-token" });
  });

  it("surfaces a JSON error instead of fabricating stream frames", async () => {
    fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ status: "error", message: "LLM not configured" }, 503),
    );
    vi.stubGlobal("fetch", fetchMock);

    const consume = async () => {
      for await (const _frame of runTeamAnalysisStream("NIFTY", "NSE_INDEX")) {
        // The error response must throw before yielding.
      }
    };

    await expect(consume()).rejects.toThrow("LLM not configured");
  });

  it("sends an explicit null preset to override the active preset", async () => {
    const body = [
      'data: {"type":"result","data":{"analysis":{"symbol":"NIFTY","exchange":"NSE_INDEX","agent_analyses":[],"consensus_signal":"HOLD","consensus_confidence":0,"consensus_reasoning":"","timestamp":"","errors":[]},"recommendation":{"symbol":"NIFTY","exchange":"NSE_INDEX","action":"HOLD","confidence":0,"reasoning":"","agent_count":0,"bullish_count":0,"bearish_count":0,"neutral_count":0,"timestamp":""}}}\n\n',
      'data: {"type":"done"}\n\n',
    ].join("");
    fetchMock = vi.fn().mockResolvedValue(
      new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    for await (const _frame of runTeamAnalysisStream("NIFTY", "NSE_INDEX", undefined, {
      mode: "flat",
      preset: null,
    })) {
      // Consume the complete stream.
    }

    expect(requestBody(fetchMock)).toMatchObject({ mode: "flat", preset: null });
  });

  it("rejects a stream that ends before its result and done frames", async () => {
    fetchMock = vi.fn().mockResolvedValue(
      new Response(
        'data: {"type":"event","event":{"task_id":"technical","agent_role":"technical","event_type":"started","data":{},"timestamp":"2026-07-10T00:00:00Z"}}\n\n',
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const consume = async () => {
      for await (const _frame of runTeamAnalysisStream("NIFTY", "NSE_INDEX")) {
        // A lifecycle-only stream is incomplete and must fail at EOF.
      }
    };

    await expect(consume()).rejects.toThrow(/ended before the final result/i);
  });
});
