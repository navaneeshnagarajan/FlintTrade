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
vi.stubEnv("DEV", "true");

import { parseResponse, post, get } from "../ftApi.helpers";

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
