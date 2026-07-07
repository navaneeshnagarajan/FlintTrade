import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/services/ftApi", () => ({
  getArbitrageScan: vi.fn(),
}));

vi.mock("@/services/api", () => ({
  getExpiry: vi.fn(),
  getMultiQuotes: vi.fn(),
  // The hook feeds getMultiQuotes' result through normaliseMultiQuotes; the
  // mocks below return already-flat Quote[] so pass-through is faithful.
  normaliseMultiQuotes: vi.fn((raw: unknown) => raw),
}));

vi.mock("@/lib/market", () => ({
  isMarketHours: vi.fn().mockReturnValue(false),
}));

import { getArbitrageScan } from "@/services/ftApi";
import { getExpiry, getMultiQuotes } from "@/services/api";
import { useArbitrageScanner, buildScanRequest, daysToExpiry } from "../useArbitrageScanner";

const mockGetArbitrageScan = getArbitrageScan as ReturnType<typeof vi.fn>;
const mockGetExpiry = getExpiry as ReturnType<typeof vi.fn>;
const mockGetMultiQuotes = getMultiQuotes as ReturnType<typeof vi.fn>;

const MONTH_NAMES = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

/** Build an expiry string N days ahead in the backend's "DD-MMM-YY" format. */
function futureExpiry(daysAhead: number): string {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() + daysAhead);
  const dd = String(d.getDate()).padStart(2, "0");
  const yy = String(d.getFullYear() % 100).padStart(2, "0");
  return `${dd}-${MONTH_NAMES[d.getMonth()]}-${yy}`;
}

function quote(symbol: string, exchange: string, ltp: number) {
  return { symbol, exchange, ltp, open: ltp, high: ltp, low: ltp, close: ltp, volume: 0 };
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("daysToExpiry", () => {
  it("parses DD-MMM-YY into whole days from today", () => {
    expect(daysToExpiry(futureExpiry(8))).toBe(8);
    expect(daysToExpiry(futureExpiry(0))).toBe(0);
  });

  it("rejects past dates and malformed strings", () => {
    expect(daysToExpiry("01-JAN-20")).toBeNull();
    expect(daysToExpiry("not-a-date")).toBeNull();
    expect(daysToExpiry("26-XYZ-99")).toBeNull();
  });
});

describe("buildScanRequest", () => {
  it("assembles real observed prices for the universe", async () => {
    const expiry = futureExpiry(8);
    const suffix = expiry.replace(/-/g, "") + "FUT";
    mockGetExpiry.mockResolvedValue({ expiry: [expiry] });
    mockGetMultiQuotes.mockResolvedValue([
      quote("NIFTY", "NSE_INDEX", 24000),
      quote(`NIFTY${suffix}`, "NFO", 24055),
      quote("RELIANCE", "NSE", 2850),
      quote("RELIANCE", "BSE", 2851.4),
      quote(`RELIANCE${suffix}`, "NFO", 2872),
    ]);

    const req = await buildScanRequest({
      universe: ["NIFTY", "reliance"],
      edgeThresholdPct: 0.5,
    });

    expect(req.edge_threshold_pct).toBe(0.5);
    expect(req.cash_future).toEqual(
      expect.arrayContaining([
        { underlying: "NIFTY", spot: 24000, future_price: 24055, days_to_expiry: 8, exchange: "NFO" },
        { underlying: "RELIANCE", spot: 2850, future_price: 2872, days_to_expiry: 8, exchange: "NFO" },
      ]),
    );
    expect(req.cross_exchange).toEqual([
      { symbol: "RELIANCE", exchange_a: "NSE", price_a: 2850, exchange_b: "BSE", price_b: 2851.4 },
    ]);
    // Futures expiry resolved per underlying on the right exchange.
    expect(mockGetExpiry).toHaveBeenCalledWith("NIFTY", "NFO", "futures");
    expect(mockGetExpiry).toHaveBeenCalledWith("RELIANCE", "NFO", "futures");
  });

  it("still scans cross-exchange gaps when futures resolution fails", async () => {
    mockGetExpiry.mockRejectedValue(new Error("expiry endpoint down"));
    mockGetMultiQuotes.mockResolvedValue([
      quote("RELIANCE", "NSE", 2850),
      quote("RELIANCE", "BSE", 2851.4),
    ]);

    const req = await buildScanRequest({ universe: ["RELIANCE"], edgeThresholdPct: 1 });

    expect(req.cash_future).toEqual([]);
    expect(req.cross_exchange).toHaveLength(1);
  });

  it("throws instead of returning an empty request when no quotes resolve", async () => {
    mockGetExpiry.mockRejectedValue(new Error("expiry endpoint down"));
    mockGetMultiQuotes.mockResolvedValue([]);

    await expect(
      buildScanRequest({ universe: ["NIFTY"], edgeThresholdPct: 1 }),
    ).rejects.toThrow(/No live quotes available/i);
  });
});

describe("useArbitrageScanner", () => {
  it("posts the assembled request and surfaces the backend response", async () => {
    const expiry = futureExpiry(5);
    const suffix = expiry.replace(/-/g, "") + "FUT";
    mockGetExpiry.mockResolvedValue({ expiry: [expiry] });
    mockGetMultiQuotes.mockResolvedValue([
      quote("NIFTY", "NSE_INDEX", 24000),
      quote(`NIFTY${suffix}`, "NFO", 24055),
    ]);
    const backendResponse = {
      is_sample_data: false,
      scan: { risk_free_rate: 0.07, edge_threshold_pct: 2, cash_future: [], cross_exchange: [] },
    };
    mockGetArbitrageScan.mockResolvedValue(backendResponse);

    const { result } = renderHook(
      () => useArbitrageScanner({ universe: ["NIFTY"], edgeThresholdPct: 2 }, true),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(backendResponse);
    expect(mockGetArbitrageScan).toHaveBeenCalledWith(
      expect.objectContaining({
        edge_threshold_pct: 2,
        cash_future: [
          { underlying: "NIFTY", spot: 24000, future_price: 24055, days_to_expiry: 5, exchange: "NFO" },
        ],
      }),
    );
  });

  it("errors (and never posts empty) when the universe has no usable quotes", async () => {
    mockGetExpiry.mockRejectedValue(new Error("down"));
    mockGetMultiQuotes.mockResolvedValue([]);

    const { result } = renderHook(
      () => useArbitrageScanner({ universe: ["NIFTY"], edgeThresholdPct: 1 }, true),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(mockGetArbitrageScan).not.toHaveBeenCalled();
  });

  it("stays idle while disconnected — no sample-churn refetches", async () => {
    const { result } = renderHook(
      () => useArbitrageScanner({ universe: ["NIFTY"], edgeThresholdPct: 1 }, false),
      { wrapper },
    );

    expect(result.current.fetchStatus).toBe("idle");
    expect(mockGetExpiry).not.toHaveBeenCalled();
    expect(mockGetMultiQuotes).not.toHaveBeenCalled();
    expect(mockGetArbitrageScan).not.toHaveBeenCalled();
  });

  it("stays idle with an empty universe", () => {
    const { result } = renderHook(
      () => useArbitrageScanner({ universe: [], edgeThresholdPct: 1 }, true),
      { wrapper },
    );

    expect(result.current.fetchStatus).toBe("idle");
    expect(mockGetArbitrageScan).not.toHaveBeenCalled();
  });
});
