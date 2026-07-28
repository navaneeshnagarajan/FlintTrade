import { render, waitFor } from "@testing-library/react";
import type { IChartApi } from "lightweight-charts";
import { useRef, type MutableRefObject } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getFtOIProfile } from "@/services/ftApi";
import { lightweightHistogramRuntime } from "@/lib/lightweightChartRuntime";
import { getNearestExpiry, useOIOverlay } from "../useOIOverlay";

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

  it("fetches the IST expiry contract, not the operator's local-midnight one", async () => {
    // 09:30 IST on Thursday 30 July 2026 — the last Thursday of the month, so
    // the contract expiring at today's close is the one to profile.
    //
    // The old calculator mixed browser-local `new Date(y, m, d)` maths with a
    // UTC `toISOString()` tail and compared `now` against LOCAL midnight of the
    // expiry day, so at this instant it asked for a contract that depended on
    // where the operator sat: "2026-08-27" from UTC (rolled a month early,
    // because local midnight had passed) and "2026-08-26" from IST (that roll,
    // plus the local-midnight-to-UTC off-by-one — a date that is not even a
    // Thursday). The answer must not depend on the host zone at all.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-07-30T04:00:00Z"));

    render(<OIOverlayHarness />);

    await waitFor(() => {
      expect(getFtOIProfile).toHaveBeenCalledWith("NIFTY", "NSE_INDEX", "2026-07-30", 20);
    });
  });
});

// ---------------------------------------------------------------------------
// Expiry contract selection
//
// Fixed instants only — the assertions must hold whatever zone the machine (or
// the CI runner) is set to, because the value drives which contract the chart
// actually requests from the backend.
// ---------------------------------------------------------------------------

describe("getNearestExpiry", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("REGRESSION: keeps the expiring contract through its own expiry day", () => {
    // 09:30 IST and 23:00 IST on Thursday 30 July 2026. The old version rolled
    // to the next month the moment local midnight passed, so the chart could
    // never overlay OI for the contract expiring that very session.
    expect(getNearestExpiry(new Date("2026-07-30T04:00:00Z"))).toBe("2026-07-30");
    expect(getNearestExpiry(new Date("2026-07-30T17:30:00Z"))).toBe("2026-07-30");
  });

  it("reads the calendar month in IST, not in UTC", () => {
    // 01:00 IST on Saturday 1 August 2026 — the UTC clock still says 31 July.
    // The IST month is August, so August's contract is the near one. (The old
    // version happened to land on the same answer here from a UTC host, and on
    // 2026-08-26 from an IST one — this pins the month read either way.)
    expect(new Date("2026-07-31T19:30:00Z").toISOString().slice(0, 10)).toBe("2026-07-31");
    expect(getNearestExpiry(new Date("2026-07-31T19:30:00Z"))).toBe("2026-08-27");
  });

  it("rolls to the next month once the expiry day is past", () => {
    expect(getNearestExpiry(new Date("2026-07-31T04:00:00Z"))).toBe("2026-08-27");
  });

  it("crosses the year boundary", () => {
    // 01:30 IST on 1 January 2027, when UTC is still on 31 December 2026.
    expect(getNearestExpiry(new Date("2026-12-31T20:00:00Z"))).toBe("2027-01-28");
    // 31 December 2026 is itself the December expiry, so it holds all day.
    expect(getNearestExpiry(new Date("2026-12-31T04:00:00Z"))).toBe("2026-12-31");
  });

  it("emits an ISO date the backend's expiry parser accepts", () => {
    expect(getNearestExpiry(new Date("2026-07-30T04:00:00Z"))).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("defaults to the current instant", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-24T19:30:00Z")); // 01:00 IST on 25 July
    expect(getNearestExpiry()).toBe("2026-07-30");
  });
});
