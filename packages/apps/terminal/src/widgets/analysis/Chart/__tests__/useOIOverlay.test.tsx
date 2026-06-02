import { render, waitFor } from "@testing-library/react";
import type { IChartApi } from "lightweight-charts";
import { useRef, type MutableRefObject } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getFtOIProfile } from "@/services/ftApi";
import { lightweightHistogramRuntime } from "@/lib/lightweightChartRuntime";
import { useOIOverlay } from "../useOIOverlay";

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
});
