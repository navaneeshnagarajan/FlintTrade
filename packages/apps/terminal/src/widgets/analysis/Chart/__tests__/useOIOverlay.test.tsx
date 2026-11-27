import { render, waitFor } from "@testing-library/react";
import type { IChartApi } from "lightweight-charts";
import { useRef, type MutableRefObject } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getFtOIProfile } from "@/services/ftApi";
import { lightweightHistogramRuntime } from "@/lib/lightweightChartRuntime";
import { getExpiry } from "@/services/api";
import { resolveOverlayExpiry, useOIOverlay } from "../useOIOverlay";

const oiSeries = {
  applyOptions: vi.fn(),
  setData: vi.fn(),
};

const priceScale = {
  applyOptions: vi.fn(),
};

const timeScale = {
  getVisibleLogicalRange: vi.fn(() => ({ from: 0, to: 12 })),
  coordinateToTime: vi.fn(() => "2026-06-01"),
};

const chart = {
  addSeries: vi.fn(() => oiSeries),
  chartElement: vi.fn(() => ({ clientWidth: 800 })),
  priceScale: vi.fn(() => priceScale),
  removeSeries: vi.fn(),
  timeScale: vi.fn(() => timeScale),
};

vi.mock("lightweight-charts", () => ({
  HistogramSeries: Symbol("HistogramSeries"),
}));

vi.mock("@/services/ftApi", () => ({
  getFtOIProfile: vi.fn(),
}));

vi.mock("@/services/api", () => ({
  getExpiry: vi.fn(),
}));

/** NIFTY contracts expire on Tuesdays; Tue 28 Jul 2026 is the July monthly. */
const NIFTY_LIST = ["21-JUL-26", "28-JUL-26", "04-AUG-26", "25-AUG-26", "2099-12-29"];

vi.mock("@/lib/lightweightChartRuntime", () => ({
  lightweightHistogramRuntime: {
    addHistogramSeries: vi.fn(() => oiSeries),
  },
}));

function OIOverlayHarness() {
  const chartRef = useRef(chart as unknown as IChartApi | null) as MutableRefObject<IChartApi | null>;
  useOIOverlay({
    chartRef,
    exchange: "NSE_INDEX",
    isVisible: true,
    symbol: "NIFTY",
  });
  return null;
}

describe("useOIOverlay", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getFtOIProfile).mockResolvedValue({
      total_ce_oi: 300,
      total_pe_oi: 100,
    } as never);
    vi.mocked(getExpiry).mockResolvedValue({ expiry: NIFTY_LIST });
  });

  it("creates the OI histogram through the shared Flint chart runtime", async () => {
    render(<OIOverlayHarness />);

    await waitFor(() => {
      expect(lightweightHistogramRuntime.addHistogramSeries).toHaveBeenCalledWith(
        chart,
        expect.objectContaining({
          priceFormat: { type: "volume" },
          priceScaleId: "oi",
        }),
      );
    });

    expect(chart.addSeries).not.toHaveBeenCalled();
    expect(priceScale.applyOptions).toHaveBeenCalledWith({
      borderVisible: false,
      scaleMargins: { top: 0.75, bottom: 0 },
    });
    expect(oiSeries.setData).toHaveBeenCalledWith([
      expect.objectContaining({
        color: "rgba(239,68,68,0.55)",
        time: "2026-06-01",
        value: expect.closeTo(66.67, 2),
      }),
    ]);
  });

  it("profiles the nearest contract on the NSE option list, read in IST", async () => {
    // 09:30 IST on Tuesday 28 July 2026, an expiry day, so the contract
    // expiring at today's close is the one to profile. The list is read from
    // the derivatives segment (NFO), not the chart's NSE_INDEX exchange.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-07-28T04:00:00Z"));

    render(<OIOverlayHarness />);

    await waitFor(() => {
      expect(getFtOIProfile).toHaveBeenCalledWith("NIFTY", "NSE_INDEX", "2026-07-28", 20);
    });
    expect(getExpiry).toHaveBeenCalledWith("NIFTY", "NFO", "options");
  });

  it("does not guess a contract when the list is empty", async () => {
    vi.mocked(getExpiry).mockResolvedValue({ expiry: [] });
    render(<OIOverlayHarness />);
    await waitFor(() => expect(getExpiry).toHaveBeenCalled());
    await Promise.resolve();
    expect(getFtOIProfile).not.toHaveBeenCalled();
  });

  it("does not guess a contract when the list cannot be loaded", async () => {
    vi.mocked(getExpiry).mockRejectedValue(new Error("network"));
    render(<OIOverlayHarness />);
    await waitFor(() => expect(getExpiry).toHaveBeenCalled());
    await Promise.resolve();
    expect(getFtOIProfile).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Expiry contract selection
//
// Fixed instants only — the assertions must hold whatever zone the machine (or
// the CI runner) is set to, because the value drives which contract the chart
// actually requests from the backend.
// ---------------------------------------------------------------------------

describe("resolveOverlayExpiry", () => {
  beforeEach(() => {
    vi.mocked(getExpiry).mockReset();
    vi.mocked(getExpiry).mockResolvedValue({ expiry: NIFTY_LIST });
  });

  it("keeps the expiring contract through its own expiry day", async () => {
    // 09:30 IST and 23:00 IST on Tuesday 28 July 2026.
    expect(await resolveOverlayExpiry("NIFTY", "NSE_INDEX", new Date("2026-07-28T04:00:00Z"))).toBe("2026-07-28");
    expect(await resolveOverlayExpiry("NIFTY", "NSE_INDEX", new Date("2026-07-28T17:30:00Z"))).toBe("2026-07-28");
  });

  it("rolls to the next listed contract once the expiry day is past, in IST", async () => {
    // 00:30 IST on Wednesday 29 July 2026; UTC still reads 28 July.
    expect(await resolveOverlayExpiry("NIFTY", "NSE_INDEX", new Date("2026-07-28T19:00:00Z"))).toBe("2026-08-04");
  });

  it("reads SENSEX Thursday expiries from the BSE option list", async () => {
    vi.mocked(getExpiry).mockResolvedValue({ expiry: ["2026-07-30", "2026-08-06"] });
    expect(await resolveOverlayExpiry("SENSEX", "BSE_INDEX", new Date("2026-07-27T04:00:00Z"))).toBe("2026-07-30");
    expect(getExpiry).toHaveBeenCalledWith("SENSEX", "BFO", "options");
  });

  it("uses a holiday-shifted date exactly as listed", async () => {
    vi.mocked(getExpiry).mockResolvedValue({ expiry: ["27-JUL-26", "04-AUG-26"] });
    expect(await resolveOverlayExpiry("NIFTY", "NSE", new Date("2026-07-24T04:00:00Z"))).toBe("2026-07-27");
  });

  it("returns null for an exchange with no option list", async () => {
    expect(await resolveOverlayExpiry("BTCUSDT", "CRYPTO")).toBeNull();
    expect(getExpiry).not.toHaveBeenCalled();
  });

  it("emits an ISO date the backend's expiry parser accepts", async () => {
    expect(await resolveOverlayExpiry("NIFTY", "NSE_INDEX", new Date("2026-07-20T04:00:00Z"))).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
