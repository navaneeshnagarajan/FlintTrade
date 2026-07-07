/**
 * getLotSize plumbing tests — the is_sample_data honesty contract.
 *
 * The backend /api/v1/screener/lot-size route serves a HARDCODED table and
 * now flags every response `is_sample_data: true`; the demo-session client
 * fallback fabricates a value locally and must flag itself the same way.
 * This value multiplies REAL order quantities in the ScalperWidget, so the
 * flag must survive the fetch layer end-to-end — a consumer that cannot see
 * it cannot refuse to size a live order from an unaudited table.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.stubEnv("DEV", true);

const mockAuthState = { token: "" };

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: { getState: () => ({ apiKey: "" }) },
}));
vi.mock("@/stores/authStore", () => ({
  useAuthStore: { getState: () => mockAuthState },
}));

import { getLotSize } from "../ftApi.screener";

function makeJsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockAuthState.token = "";
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getLotSize — is_sample_data flag survives end-to-end", () => {
  it("passes the backend stub's is_sample_data flag through to the caller", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeJsonResponse({
        symbol: "FINNIFTY",
        exchange: "NFO",
        lot_size: 65,
        is_sample_data: true,
      }),
    );

    const result = await getLotSize("FINNIFTY", "NFO");

    expect(result.lot_size).toBe(65);
    expect(result.is_sample_data).toBe(true);
  });

  it("flags the demo-session fallback as sample data", async () => {
    mockAuthState.token = "demo-user";

    const result = await getLotSize("NIFTY", "NFO");

    // No network call — the demo fallback is fabricated on the client and
    // must declare itself so no consumer mistakes it for the symbol master.
    expect(fetch).not.toHaveBeenCalled();
    expect(result.lot_size).toBe(75);
    expect(result.is_sample_data).toBe(true);
  });
});
