import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: { getState: () => ({ apiKey: "" }) },
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: "" }) },
}));

import { getOrderFlow } from "../ftApi.data";

function jsonResponse(data: unknown): Response {
  return new Response(JSON.stringify({ status: "success", data }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

const validBucket = {
  time_label: "09:15:00",
  cells: {
    "22500": { buy_volume: 100, sell_volume: 80 },
  },
  poc_price: 22_500,
  total_volume: 180,
  delta: 20,
  quality: "exact",
  provenance: "trade_tick",
};

const sampleBucket = {
  ...validBucket,
  quality: "sample",
  provenance: "synthetic",
};

const validResponse = {
  buckets: [validBucket],
  symbol: "NIFTY",
  exchange: "NSE_INDEX",
  interval: 300,
  is_live: true,
  is_sample_data: false,
  quality: "exact",
  provenance: "trade_tick",
  tick_size: 0.05,
  requested_tick_size: 0.05,
  source_tick_size: 0.05,
  live_state: "live",
  freshness: {
    state: "live",
    is_fresh: true,
    last_tick_timestamp: 1_786_811_400,
    last_tick_session: "2026-08-15",
    current_session: "2026-08-15",
    age_seconds: 1,
  },
};

describe("getOrderFlow runtime validation", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("accepts a well-formed exact trade-tick response", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(validResponse));

    await expect(getOrderFlow("NIFTY", "NSE_INDEX", 20, 300, 0.05)).resolves.toEqual(
      validResponse,
    );
  });

  it.each([-0.25, -5])("accepts backend-permitted freshness clock skew of %ss", async (ageSeconds) => {
    const response = {
      ...validResponse,
      freshness: { ...validResponse.freshness, age_seconds: ageSeconds },
    };
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(response));

    await expect(getOrderFlow("NIFTY", "NSE_INDEX", 20, 300, 0.05)).resolves.toEqual(response);
  });

  it("accepts a coherent delayed response with a negative age beyond five seconds", async () => {
    const response = {
      ...validResponse,
      is_live: false,
      live_state: "delayed",
      freshness: {
        ...validResponse.freshness,
        state: "delayed",
        is_fresh: false,
        age_seconds: -30,
      },
    };
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(response));

    await expect(getOrderFlow("NIFTY", "NSE_INDEX", 20, 300, 0.05)).resolves.toEqual(response);
  });

  it("accepts the backend's coherent synthetic warming state", async () => {
    const response = {
      ...validResponse,
      buckets: [{ ...validBucket, quality: "sample", provenance: "synthetic" }],
      is_live: false,
      is_sample_data: true,
      quality: "sample",
      provenance: "synthetic",
      live_state: "warming",
    };
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(response));

    await expect(getOrderFlow("NIFTY", "NSE_INDEX", 20, 300, 0.05)).resolves.toEqual(response);
  });

  it.each([
    [
      "live freshness age beyond the backend clock-skew tolerance",
      {
        ...validResponse,
        freshness: { ...validResponse.freshness, age_seconds: -5.001 },
      },
    ],
    [
      "is_live=false with live_state=live",
      { ...validResponse, is_live: false },
    ],
    [
      "live freshness marked as not fresh",
      {
        ...validResponse,
        freshness: { ...validResponse.freshness, is_fresh: false },
      },
    ],
    [
      "is_live=true with delayed freshness",
      {
        ...validResponse,
        freshness: { ...validResponse.freshness, state: "delayed", is_fresh: false },
      },
    ],
    [
      "live_state that disagrees with freshness.state",
      {
        ...validResponse,
        is_live: false,
        live_state: "delayed",
        freshness: { ...validResponse.freshness, state: "stale", is_fresh: false },
      },
    ],
    [
      "non-live freshness marked as fresh",
      {
        ...validResponse,
        is_live: false,
        live_state: "delayed",
        freshness: { ...validResponse.freshness, state: "delayed", is_fresh: true },
      },
    ],
  ])("rejects contradictory %s", async (_caseName, payload) => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(payload));

    await expect(
      getOrderFlow("NIFTY", "NSE_INDEX", 20, 300, 0.05),
    ).rejects.toThrow(/invalid order-flow response/i);
  });

  it.each([
    [
      "non-array buckets",
      { ...validResponse, buckets: { bad: validBucket } },
    ],
    [
      "non-object cells",
      { ...validResponse, buckets: [{ ...validBucket, cells: [] }] },
    ],
    [
      "non-numeric cell volume",
      {
        ...validResponse,
        buckets: [{
          ...validBucket,
          cells: { "22500": { buy_volume: "100", sell_volume: 80 } },
        }],
      },
    ],
    [
      "exact synthetic provenance",
      {
        ...validResponse,
        is_live: false,
        is_sample_data: true,
        quality: "exact",
        provenance: "synthetic",
        live_state: "unavailable",
        buckets: [{ ...validBucket, quality: "exact", provenance: "synthetic" }],
      },
    ],
    [
      "a synthetic sample bucket under a live mixed response",
      {
        ...validResponse,
        buckets: [validBucket, sampleBucket],
        quality: "estimated",
        provenance: "mixed",
      },
    ],
    [
      "a synthetic sample bucket under a delayed non-sample response",
      {
        ...validResponse,
        buckets: [validBucket, sampleBucket],
        is_live: false,
        quality: "estimated",
        provenance: "mixed",
        live_state: "delayed",
        freshness: {
          ...validResponse.freshness,
          state: "delayed",
          is_fresh: false,
          age_seconds: 30,
        },
      },
    ],
  ])("rejects %s", async (_caseName, payload) => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(payload));

    await expect(
      getOrderFlow("NIFTY", "NSE_INDEX", 20, 300, 0.05),
    ).rejects.toThrow(/invalid order-flow response/i);
  });
});
