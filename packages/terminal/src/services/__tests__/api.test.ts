import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ---------------------------------------------------------------------------
// Mock Zustand stores and rate limiters BEFORE importing the module under test.
// vi.mock is hoisted by Vitest, so the factories run before any import.
// ---------------------------------------------------------------------------

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: {
    getState: () => ({ host: "http://localhost:5000", apiKey: "test-key-123" }),
  },
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: {
    getState: () => ({ mode: "live" }),
  },
}));

vi.mock("@/services/rateLimiter", () => ({
  orderLimiter: { tryConsume: vi.fn(() => true) },
  smartOrderLimiter: { tryConsume: vi.fn(() => true) },
  generalLimiter: { tryConsume: vi.fn(() => true) },
}));

// Now import the functions under test and the mocked limiters
import {
  placeOrder,
  cancelAllOrders,
  getQuotes,
  getIntervals,
  getFunds,
  ping,
  searchSymbol,
  getPositionbook,
} from "../api";
import {
  orderLimiter,
  generalLimiter,
} from "@/services/rateLimiter";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("OpenAlgo API client (api.ts)", () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let fetchSpy: any;

  beforeEach(() => {
    fetchSpy = vi.spyOn(globalThis, "fetch");
    // Reset rate limiter mocks to allow requests by default
    vi.mocked(orderLimiter.tryConsume).mockReturnValue(true);
    vi.mocked(generalLimiter.tryConsume).mockReturnValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ---- POST requests ----

  it("POST request sends JSON body with apikey", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { available: 50000 } }),
    );

    await getFunds();

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/funds");
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual(
      expect.objectContaining({ "Content-Type": "application/json" }),
    );
    const body = JSON.parse(init.body as string);
    expect(body).toHaveProperty("apikey", "test-key-123");
  });

  it("POST sends extra params merged with apikey", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { ltp: 22500 } }),
    );

    await getQuotes("NIFTY", "NSE_INDEX");

    const body = JSON.parse(
      (fetchSpy.mock.calls[0] as [string, RequestInit])[1].body as string,
    );
    expect(body).toMatchObject({
      apikey: "test-key-123",
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
    });
  });

  // ---- GET requests ----

  it("GET request does not send a body or Content-Type", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: ["1m", "5m", "1h"] }),
    );

    const result = await getIntervals();

    expect(result).toEqual(["1m", "5m", "1h"]);
    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit | undefined];
    // GET calls use the single-arg form of fetch (no init or no method)
    expect(init).toBeUndefined();
  });

  // ---- postOrder — mode header ----

  it("postOrder attaches X-FlintTrade-Mode header from modeStore", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { orderId: "ORD-1" } }),
    );

    await placeOrder({
      symbol: "RELIANCE",
      exchange: "NSE",
      action: "BUY",
      quantity: 1,
      price_type: "MARKET",
      product: "MIS",
      orderType: "MARKET",
    } as unknown as Parameters<typeof placeOrder>[0]);

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/orders/place");
    const headers = init.headers as Record<string, string>;
    expect(headers["X-FlintTrade-Mode"]).toBe("live");
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("postOrder does NOT include apikey in the body (backend injects it)", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { orderId: "ORD-2" } }),
    );

    await cancelAllOrders("TestStrategy");

    const body = JSON.parse(
      (fetchSpy.mock.calls[0] as [string, RequestInit])[1].body as string,
    );
    expect(body).not.toHaveProperty("apikey");
    expect(body).toHaveProperty("strategy", "TestStrategy");
  });

  // ---- Response unwrapping ----

  it("unwraps { data: X } from successful response", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { status: "pong" } }),
    );

    const result = await ping();
    expect(result).toEqual({ status: "pong" });
  });

  it("falls back to raw json when data key is absent", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", ltp: 100 }),
    );

    const result = await getQuotes("INFY", "NSE");
    // When no `data` key, returns entire json
    expect(result).toHaveProperty("ltp", 100);
  });

  it("unwraps nested arrays (positionbook with positions key)", async () => {
    const positions = [{ symbol: "NIFTY", quantity: 50 }];
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { positions } }),
    );

    const result = await getPositionbook();
    expect(result).toEqual(positions);
  });

  // ---- Error responses ----

  it("throws on 401 with descriptive message", async () => {
    fetchSpy.mockResolvedValueOnce(jsonResponse({ message: "Unauthorized" }, 401));

    await expect(getQuotes("NIFTY", "NSE")).rejects.toThrow(
      "API key invalid. Check Settings → Connection.",
    );
  });

  it("throws on 500 with server message when available", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ error: "DB connection lost" }, 500),
    );

    await expect(getFunds()).rejects.toThrow("DB connection lost");
  });

  it("throws generic message for unexpected status codes", async () => {
    fetchSpy.mockResolvedValueOnce(jsonResponse({}, 429));

    await expect(getFunds()).rejects.toThrow("Server error (429)");
  });

  it("throws on status: error in JSON body", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "error", message: "Symbol not found" }),
    );

    await expect(getQuotes("INVALID", "NSE")).rejects.toThrow("Symbol not found");
  });

  // ---- Network errors ----

  it("throws descriptive error on network failure (POST)", async () => {
    fetchSpy.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(getFunds()).rejects.toThrow(
      "Connection failed. Check OpenAlgo is running.",
    );
  });

  it("throws descriptive error on network failure (postOrder)", async () => {
    fetchSpy.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(placeOrder({} as Parameters<typeof placeOrder>[0])).rejects.toThrow(
      "Connection failed. Check FlintTrade backend is running.",
    );
  });

  // ---- Rate limiting ----

  it("throws when general rate limiter is exhausted (POST)", async () => {
    vi.mocked(generalLimiter.tryConsume).mockReturnValue(false);

    await expect(getFunds()).rejects.toThrow("Rate limit exceeded");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("throws when order rate limiter is exhausted (postOrder)", async () => {
    vi.mocked(orderLimiter.tryConsume).mockReturnValue(false);

    await expect(
      placeOrder({} as Parameters<typeof placeOrder>[0]),
    ).rejects.toThrow("Rate limit exceeded");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  // ---- Input sanitisation ----

  it("searchSymbol sanitises query and sends POST", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: [{ symbol: "RELIANCE", exchange: "NSE" }] }),
    );

    const result = await searchSymbol("RELIANCE<script>");
    expect(result).toEqual([{ symbol: "RELIANCE", exchange: "NSE" }]);

    const body = JSON.parse(
      (fetchSpy.mock.calls[0] as [string, RequestInit])[1].body as string,
    );
    // angle brackets stripped by the sanitiser
    expect(body.query).not.toContain("<");
    expect(body.query).not.toContain(">");
  });
});
