/**
 * Max-pain / PCR / ATM lifecycle tests for useOIOverlay.
 *
 * Kept separate from useOIOverlay.test.tsx: these mocks hand out a FRESH
 * series object per creation call, so the stale-run guard and the max-pain
 * carrier lifecycle (created when the payload has max_pain_strike, removed on
 * toggle-off/unmount/symbol change) can be asserted against real object
 * identities rather than one shared mock.
 */

import { render, waitFor } from "@testing-library/react";
import type { IChartApi } from "lightweight-charts";
import { useRef, type MutableRefObject } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { lightweightHistogramRuntime, lightweightLineRuntime } from "@/lib/lightweightChartRuntime";
import { getFtOIProfile } from "@/services/ftApi";
import type { OIProfileData } from "@/types/api";
import { useOIOverlay } from "../useOIOverlay";

interface SeriesMock {
  applyOptions: ReturnType<typeof vi.fn>;
  setData: ReturnType<typeof vi.fn>;
  createPriceLine: ReturnType<typeof vi.fn>;
}

function makeSeriesMock(): SeriesMock {
  return {
    applyOptions: vi.fn(),
    setData: vi.fn(),
    createPriceLine: vi.fn(() => ({})),
  };
}

const histogramSeries: SeriesMock[] = [];
const carrierSeries: SeriesMock[] = [];

const priceScale = { applyOptions: vi.fn() };

const timeScale = {
  getVisibleLogicalRange: vi.fn(() => ({ from: 0, to: 12 })),
  coordinateToTime: vi.fn(() => "2026-06-01"),
};

const chart = {
  chartElement: vi.fn(() => ({ clientWidth: 800 })),
  priceScale: vi.fn(() => priceScale),
  removeSeries: vi.fn(),
  timeScale: vi.fn(() => timeScale),
};

vi.mock("@/services/ftApi", () => ({
  getFtOIProfile: vi.fn(),
}));

vi.mock("@/lib/lightweightChartRuntime", () => ({
  lightweightHistogramRuntime: {
    addHistogramSeries: vi.fn(() => {
      const series = makeSeriesMock();
      histogramSeries.push(series);
      return series;
    }),
  },
  lightweightLineRuntime: {
    addLineSeries: vi.fn(() => {
      const series = makeSeriesMock();
      carrierSeries.push(series);
      return series;
    }),
  },
}));

function makeProfile(overrides: Partial<OIProfileData> = {}): OIProfileData {
  return {
    underlying: "NIFTY",
    expiry: "2026-07-30",
    spot_price: 24012.4,
    atm_strike: 24000,
    max_pain_strike: 23950,
    strikes: [],
    total_ce_oi: 300,
    total_pe_oi: 252,
    pcr: 0.84,
    ...overrides,
  };
}

function Harness({ isVisible = true, symbol = "NIFTY" }: { isVisible?: boolean; symbol?: string }) {
  const chartRef = useRef(chart as unknown as IChartApi | null) as MutableRefObject<IChartApi | null>;
  useOIOverlay({
    chartRef,
    exchange: "NSE_INDEX",
    isVisible,
    symbol,
  });
  return null;
}

const ATM_LABEL = (24000).toLocaleString("en-IN", { maximumFractionDigits: 2 });

describe("useOIOverlay max-pain / PCR / ATM surfaces", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    histogramSeries.length = 0;
    carrierSeries.length = 0;
    vi.mocked(getFtOIProfile).mockResolvedValue(makeProfile());
  });

  it("requests a compact ATM-centred strike window from the profile endpoint", async () => {
    render(<Harness />);

    await waitFor(() => {
      expect(getFtOIProfile).toHaveBeenCalledWith(
        "NIFTY",
        "NSE_INDEX",
        expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
        20,
      );
    });
  });

  it("draws the max-pain strike as a dashed price line on the main price scale", async () => {
    render(<Harness />);

    await waitFor(() => expect(carrierSeries.length).toBeGreaterThan(0));
    const carrier = carrierSeries.at(-1);
    if (!carrier) throw new Error("carrier series not created");

    // The carrier is visually inert and lives on the candle scale, not "oi".
    expect(lightweightLineRuntime.addLineSeries).toHaveBeenCalledWith(
      chart,
      expect.objectContaining({
        color: "transparent",
        lineVisible: false,
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
        priceScaleId: "right",
      }),
    );

    // …and must never stretch the candle autoscale via its anchor point.
    const lastCall = vi.mocked(lightweightLineRuntime.addLineSeries).mock.calls.at(-1);
    const options = lastCall?.[1] as { autoscaleInfoProvider: () => unknown };
    expect(options.autoscaleInfoProvider()).toBeNull();

    // Price lines only render once the series has data: one anchor point.
    expect(carrier.setData).toHaveBeenCalledWith([{ time: "2026-06-01", value: 23950 }]);

    expect(carrier.createPriceLine).toHaveBeenCalledWith({
      price: 23950,
      color: expect.any(String),
      lineWidth: 1,
      lineStyle: 2, // lightweight-charts dashed code
      axisLabelVisible: true,
      title: "Max pain",
    });
  });

  it("surfaces PCR and the ATM strike through the histogram's axis title", async () => {
    render(<Harness />);

    await waitFor(() => {
      const series = histogramSeries.at(-1);
      if (!series) throw new Error("histogram series not created");
      expect(series.setData).toHaveBeenCalled();
    });

    const series = histogramSeries.at(-1);
    expect(series?.applyOptions).toHaveBeenCalledWith({
      title: `OI PCR 0.84 · ATM ${ATM_LABEL}`,
    });
  });

  it("skips the price line and the PCR readout when the payload lacks them", async () => {
    // NaN stands in for the backend's null PCR (zero total CE OI) and for a
    // payload with no usable max-pain strike.
    vi.mocked(getFtOIProfile).mockResolvedValue(
      makeProfile({ max_pain_strike: Number.NaN, pcr: Number.NaN }),
    );

    render(<Harness />);

    await waitFor(() => {
      const series = histogramSeries.at(-1);
      if (!series) throw new Error("histogram series not created");
      expect(series.setData).toHaveBeenCalled();
    });

    expect(lightweightLineRuntime.addLineSeries).not.toHaveBeenCalled();
    // The ATM strike still shows; the non-finite PCR part is dropped.
    expect(histogramSeries.at(-1)?.applyOptions).toHaveBeenCalledWith({
      title: `OI ATM ${ATM_LABEL}`,
    });
  });

  it("removes the max-pain carrier on toggle-off", async () => {
    const { rerender } = render(<Harness isVisible />);

    await waitFor(() => expect(carrierSeries.length).toBeGreaterThan(0));
    const carrier = carrierSeries.at(-1);
    expect(chart.removeSeries).not.toHaveBeenCalledWith(carrier);

    rerender(<Harness isVisible={false} />);

    expect(chart.removeSeries).toHaveBeenCalledWith(carrier);
  });

  it("removes the max-pain carrier on unmount", async () => {
    const { unmount } = render(<Harness />);

    await waitFor(() => expect(carrierSeries.length).toBeGreaterThan(0));
    const carrier = carrierSeries.at(-1);

    unmount();

    expect(chart.removeSeries).toHaveBeenCalledWith(carrier);
  });

  it("replaces the max-pain carrier when the symbol changes", async () => {
    const { rerender } = render(<Harness symbol="NIFTY" />);

    await waitFor(() => expect(carrierSeries.length).toBeGreaterThan(0));
    const first = carrierSeries.at(-1);
    const countBefore = carrierSeries.length;

    rerender(<Harness symbol="BANKNIFTY" />);

    await waitFor(() => expect(carrierSeries.length).toBeGreaterThan(countBefore));
    expect(chart.removeSeries).toHaveBeenCalledWith(first);
    expect(carrierSeries.at(-1)?.createPriceLine).toHaveBeenCalledWith(
      expect.objectContaining({ price: 23950, title: "Max pain" }),
    );
  });

  it("still creates the OI histogram exactly as before (regression)", async () => {
    render(<Harness />);

    await waitFor(() => {
      expect(lightweightHistogramRuntime.addHistogramSeries).toHaveBeenCalledWith(
        chart,
        expect.objectContaining({
          priceFormat: { type: "volume" },
          priceScaleId: "oi",
        }),
      );
    });

    await waitFor(() => {
      const series = histogramSeries.at(-1);
      if (!series) throw new Error("histogram series not created");
      expect(series.setData).toHaveBeenCalledWith([
        expect.objectContaining({
          color: "rgba(239,68,68,0.55)",
          time: "2026-06-01",
          value: expect.closeTo(16, 2), // |300 − 252| / 300 × 100
        }),
      ]);
    });
  });
});
