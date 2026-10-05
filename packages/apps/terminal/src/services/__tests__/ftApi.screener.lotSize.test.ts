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

import { lotSizeFromMaster } from "@/lib/instrumentLots";
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

  it("labels demo lots as Example and reads the instrument master", async () => {
    mockAuthState.token = "demo-user";

    const nifty = await getLotSize("NIFTY", "NFO");
    const bank = await getLotSize("BANKNIFTY", "NFO");
    const sensex = await getLotSize("SENSEX", "BFO");
    const finnifty = await getLotSize("FINNIFTY", "NFO");
    const nxt = await getLotSize("NIFTYNXT50", "NFO");

    // No network call — demo rows are examples from the cached master.
    expect(fetch).not.toHaveBeenCalled();
    expect(nifty.lot_size).toBe(lotSizeFromMaster("NIFTY"));
    expect(nifty.lot_size).toBeGreaterThan(0);
    expect(nifty.example_label).toBe("Example");
    expect(nifty.is_sample_data).toBe(true);
    expect(JSON.stringify(nifty)).not.toMatch(/expiry/i);
    expect(bank.lot_size).toBe(lotSizeFromMaster("BANKNIFTY"));
    expect(bank.example_label).toBe("Example");
    expect(JSON.stringify(bank)).not.toMatch(/expiry/i);
    expect(sensex.lot_size).toBe(lotSizeFromMaster("SENSEX"));
    expect(sensex.example_label).toBe("Example");
    expect(JSON.stringify(sensex)).not.toMatch(/expiry/i);
    expect(finnifty.lot_size).toBe(0);
    expect(finnifty.example_label).toBeUndefined();
    expect(nxt.lot_size).toBe(0);
    expect(nxt.example_label).toBeUndefined();
  });
});
