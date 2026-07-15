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

import { FtApiError, parseResponse, post, get, getV1, putV1, delV1 } from "../ftApi.helpers";
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
// parseResponse — sibling is_sample_data propagation (honesty affordance)
// ---------------------------------------------------------------------------

describe("parseResponse — is_sample_data survives the data-unwrap", () => {
  it("propagates a sibling is_sample_data: true onto the unwrapped object payload", async () => {
    // Backend pattern used by option-chain analytics (gex, gammadensity,
    // volsurface…) and earnings: the flag sits BESIDE data. Discarding it
    // rendered synthetic spot-24000 chains as live in connected widgets.
    const res = makeJsonResponse({
      status: "success",
      is_sample_data: true,
      data: { spot: 24000, gamma_flip: 24000 },
    });
    const result = await parseResponse<{ spot: number; is_sample_data?: boolean }>(res, "gex");
    expect(result).toStrictEqual({ spot: 24000, gamma_flip: 24000, is_sample_data: true });
  });

  it("does not add the flag when the envelope does not declare sample data", async () => {
    const res = makeJsonResponse({ status: "success", data: { spot: 24000 } });
    const result = await parseResponse<{ spot: number }>(res, "gex");
    expect(result).toStrictEqual({ spot: 24000 });
  });

  it("propagates a sibling is_sample_data: false as explicit live provenance", async () => {
    const res = makeJsonResponse({
      status: "success",
      is_sample_data: false,
      data: { spot: 24000 },
    });
    const result = await parseResponse<{ spot: number; is_sample_data: boolean }>(res, "gex");
    expect(result).toStrictEqual({ spot: 24000, is_sample_data: false });
  });

  it("fail-closed: an envelope-level true overrides a nested false", async () => {
    const res = makeJsonResponse({
      status: "success",
      is_sample_data: true,
      data: { spot: 24000, is_sample_data: false },
    });
    const result = await parseResponse<{ is_sample_data?: boolean }>(res, "gex");
    expect(result.is_sample_data).toBe(true);
  });

  it("preserves a nested true when it is already inside data", async () => {
    const res = makeJsonResponse({
      status: "success",
      is_sample_data: true,
      data: { entries: [], is_sample_data: true },
    });
    const result = await parseResponse<{ is_sample_data?: boolean }>(res, "earnings/calendar");
    expect(result.is_sample_data).toBe(true);
  });

  it("leaves array payloads untouched (flag cannot attach without a shape change)", async () => {
    const res = makeJsonResponse({
      status: "success",
      is_sample_data: true,
      data: [{ symbol: "NIFTY" }],
    });
    const result = await parseResponse<Array<{ symbol: string }>>(res, "positions");
    expect(result).toStrictEqual([{ symbol: "NIFTY" }]);
  });

  it("leaves unenveloped responses untouched (flag already at top level survives)", async () => {
    const res = makeJsonResponse({ rates: [], is_sample_data: true });
    const result = await parseResponse<{ rates: unknown[]; is_sample_data: boolean }>(
      res,
      "crypto/funding_rates",
    );
    expect(result).toStrictEqual({ rates: [], is_sample_data: true });
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

  it("surfaces the backend's actionable message from a non-ok JSON body", async () => {
    // The backend's {status, message} bodies tell the operator exactly what
    // to fix (enable a flag, grant an ACL) — they must not collapse to a
    // bare "HTTP 403".
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "error",
          message: "Smart routing is disabled. Enable it via workspace.json brokers.smart_routing.enabled.",
        }),
        { status: 403, headers: { "Content-Type": "application/json" } },
      ),
    );
    await expect(post("orders/smart-route", {})).rejects.toThrow(
      "Smart routing is disabled",
    );
  });

  it("preserves the HTTP status and structured data from a non-ok JSON body", async () => {
    const pending = {
      resolution_id: "resolution-1",
      attempt_id: "attempt-1",
      status: "PENDING_ROUTER_CLEAR",
    };
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeJsonResponse(
        {
          status: "error",
          message: "Decision recorded; outcome remains blocked pending exact router clear",
          data: pending,
        },
        503,
      ),
    );

    const error = await post("reconciliation/outcomes/attempt-1/resolve", {}).catch(
      (caught: unknown) => caught,
    );

    expect(error).toBeInstanceOf(FtApiError);
    expect(error).toMatchObject({ status: 503, data: pending });
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

  it("forwards an AbortSignal to fetch", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeJsonResponse({ data: null }),
    );
    const controller = new AbortController();

    await post("oiprofile", {}, controller.signal);

    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(init.signal).toBe(controller.signal);
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
// Bare /v1 helpers
// ---------------------------------------------------------------------------

describe("bare /v1 helpers — shared gateway route client", () => {
  it("getV1 surfaces non-ok JSON error fields", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeJsonResponse({ status: "error", error: "Gateway unavailable" }, 503),
    );

    await expect(getV1("brokers")).rejects.toThrow("Gateway unavailable");
  });

  it("putV1 sends JSON to the bare /v1 route family", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeJsonResponse({ status: "success", limits: { dhan: { order: 10, data: 2 } } }),
    );

    const result = await putV1<{ limits: Record<string, { order: number; data: number }> }>(
      "rate-limits",
      { broker_id: "dhan", order: 10 },
    );

    expect(result.limits.dhan.order).toBe(10);
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/ft-api/v1/rate-limits");
    expect(init.method).toBe("PUT");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual({ broker_id: "dhan", order: 10 });
  });

  it("delV1 sends DELETE without a JSON content header", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeJsonResponse({ status: "success" }),
    );

    await delV1("accounts/acc%2Fspecial");

    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/ft-api/v1/accounts/acc%2Fspecial");
    expect(init.method).toBe("DELETE");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
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

  it("attaches X-API-Key independently when only apiKey is set", async () => {
    // Locks the contract that the two headers attach independently —
    // a regression where buildHeaders required *both* to be present to
    // attach *either* would be caught here.
    (useConnectionStore.getState as unknown as ReturnType<typeof vi.fn>) = vi.fn(() => ({
      apiKey: "only-key",
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
    expect(headers["X-API-Key"]).toBe("only-key");
    expect(headers["Authorization"]).toBeUndefined();
  });

  it("attaches Authorization independently when only token is set", async () => {
    (useConnectionStore.getState as unknown as ReturnType<typeof vi.fn>) = vi.fn(() => ({
      apiKey: "",
    }));
    (useAuthStore.getState as unknown as ReturnType<typeof vi.fn>) = vi.fn(() => ({
      token: "only-jwt",
    }));
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeJsonResponse({ data: null }),
    );

    await post("safety/config", {});

    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-API-Key"]).toBeUndefined();
    expect(headers["Authorization"]).toBe("Bearer only-jwt");
  });
});
