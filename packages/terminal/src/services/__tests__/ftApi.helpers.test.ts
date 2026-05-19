/**
 * ftApi.helpers.ts unit tests
 *
 * `ftApi.helpers.ts` is the foundation of all 12 split `ftApi.*.ts`
 * service modules — every one of them imports `post`/`get`/`put`/`del`
 * from here, and every successful response runs through `parseResponse`.
 * A bug in any of these helpers manifests as a cross-cutting frontend
 * outage, so the tests here aim to lock the contract.
 *
 * `fetch` is stubbed via `vi.stubGlobal` so no real network calls are made.
 * `import.meta.env.DEV` is stubbed to `"true"` so `getBase()` returns the
 * Vite-proxy prefix (`/ft-api`) rather than an empty string.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Force DEV mode so getBase() returns "/ft-api". Stub before the helper
// import because Vite inlines `import.meta.env.DEV` at module-load time.
vi.stubEnv("DEV", true);

// The helpers now read X-API-Key from connectionStore and the JWT from
// authStore on every call, so each test mocks both stores to return empty
// values by default. Individual tests override via getState mocks.
vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: { getState: () => ({ apiKey: "" }) },
}));
vi.mock("@/stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: "" }) },
}));

import { parseResponse, post, get } from "../ftApi.helpers";
import { useConnectionStore } from "@/stores/connectionStore";
import { useAuthStore } from "@/stores/authStore";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeJsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// parseResponse
// ---------------------------------------------------------------------------

describe("parseResponse — data unwrapping", () => {
  it("returns json.data when the response has a data field", async () => {
    const res = makeJsonResponse({ status: "success", data: { availableCash: 50000 } });
    const result = await parseResponse<{ availableCash: number }>(res, "funds");
    expect(result).toStrictEqual({ availableCash: 50000 });
  });

  it("returns the raw json when there is no data wrapper", async () => {
    const res = makeJsonResponse([{ symbol: "NIFTY" }]);
    const result = await parseResponse<Array<{ symbol: string }>>(res, "positions");
    expect(result).toStrictEqual([{ symbol: "NIFTY" }]);
  });

  it("throws an Error when json.status is 'error'", async () => {
    const res = makeJsonResponse({ status: "error", message: "Invalid API key" });
    await expect(parseResponse(res, "funds")).rejects.toThrow("Invalid API key");
  });

  it("throws a generic message when status is error but no message field", async () => {
    const res = makeJsonResponse({ status: "error" });
    await expect(parseResponse(res, "test-endpoint")).rejects.toThrow(
      "FT API test-endpoint error",
    );
  });
});

// ---------------------------------------------------------------------------
// post
// ---------------------------------------------------------------------------

describe("post — HTTP error handling", () => {
  it("throws when the server returns a non-ok status", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response("", { status: 500 }),
    );
    await expect(post("safety/config", {})).rejects.toThrow("FT API safety/config: HTTP 500");
  });

  it("sends Content-Type application/json", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeJsonResponse({ data: { ok: true } }),
    );
    await post("safety/config", { key: "value" });
    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });

  it("calls the correct URL with the ft-api prefix", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeJsonResponse({ data: null }),
    );
    await post("ditto/risk", {});
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toBe("/ft-api/api/v1/ditto/risk");
  });
});

// ---------------------------------------------------------------------------
// get
// ---------------------------------------------------------------------------

describe("get — HTTP error handling", () => {
  it("throws when the server returns a non-ok status", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response("", { status: 404 }),
    );
    await expect(get("ditto/accounts")).rejects.toThrow("FT API ditto/accounts: HTTP 404");
  });

  it("returns unwrapped data on success", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeJsonResponse({ data: { accounts: [] } }),
    );
    const result = await get<{ accounts: unknown[] }>("ditto/accounts");
    expect(result).toStrictEqual({ accounts: [] });
  });
});

// ---------------------------------------------------------------------------
// Auth header attachment — regression for Codex stop-gate finding
// "Preserve auth headers for bracket order placement"
// ---------------------------------------------------------------------------

describe("buildHeaders — auth attachment", () => {
  it("post attaches X-API-Key and Authorization Bearer when stores are populated", async () => {
    // Re-mock the store getters for this test only.
    (useConnectionStore.getState as unknown as ReturnType<typeof vi.fn>) = vi.fn(() => ({
      apiKey: "test-openalgo-key",
    }));
    (useAuthStore.getState as unknown as ReturnType<typeof vi.fn>) = vi.fn(() => ({
      token: "test-jwt-abc",
    }));
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeJsonResponse({ data: { ok: true } }),
    );

    await post("orders/bracket", { entry: { symbol: "NIFTY" } });

    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-API-Key"]).toBe("test-openalgo-key");
    expect(headers["Authorization"]).toBe("Bearer test-jwt-abc");
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("get attaches auth headers but no Content-Type", async () => {
    (useConnectionStore.getState as unknown as ReturnType<typeof vi.fn>) = vi.fn(() => ({
      apiKey: "k",
    }));
    (useAuthStore.getState as unknown as ReturnType<typeof vi.fn>) = vi.fn(() => ({
      token: "t",
    }));
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeJsonResponse({ data: [] }),
    );

    await get("positions");

    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    const headers = init?.headers as Record<string, string>;
    expect(headers["X-API-Key"]).toBe("k");
    expect(headers["Authorization"]).toBe("Bearer t");
    expect(headers["Content-Type"]).toBeUndefined();
  });

  it("omits both headers when stores are empty", async () => {
    (useConnectionStore.getState as unknown as ReturnType<typeof vi.fn>) = vi.fn(() => ({
      apiKey: "",
    }));
    (useAuthStore.getState as unknown as ReturnType<typeof vi.fn>) = vi.fn(() => ({
      token: "",
    }));
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeJsonResponse({ data: null }),
    );

    await post("safety/config", {});

    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-API-Key"]).toBeUndefined();
    expect(headers["Authorization"]).toBeUndefined();
    expect(headers["Content-Type"]).toBe("application/json");
  });
});
