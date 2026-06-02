import { render, waitFor } from "@testing-library/react";
import type { IChartApi, ISeriesApi, Time } from "lightweight-charts";
import { useRef, type MutableRefObject } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  FLINT_CHART_DEFAULT_INDICATORS,
  FLINT_CHART_DEFAULT_PERIODS,
  FLINT_CHART_INDICATOR_DEFAULT_COLORS,
  FLINT_CHART_INDICATOR_DEFAULT_LINE_STYLES,
  FLINT_CHART_INDICATOR_DEFAULT_PANE_SIZES,
  FLINT_CHART_INDICATOR_DEFAULT_PANE_STRETCH_FACTORS,
} from "@flinttrade/design-system";
import type { FlintChartOhlcvBar as OhlcvBar } from "@flinttrade/design-system";
import {
  lightweightHistogramRuntime,
  lightweightLineRuntime,
} from "@/lib/lightweightChartRuntime";
import type { IndicatorSeriesRefs, IndicatorState } from "../types";
import { useIndicators } from "../useIndicators";

const indicatorRuntimeMocks = vi.hoisted(() => {
  const createLineSeries = () => ({
    applyOptions: vi.fn(),
    setData: vi.fn(),
  });
  const createHistogramSeries = () => ({
    applyOptions: vi.fn(),
    setData: vi.fn(),
  });
  const createdLineSeries: Array<ReturnType<typeof createLineSeries>> = [];
  const createdHistogramSeries: Array<ReturnType<typeof createHistogramSeries>> = [];
  const volumeSeries = createHistogramSeries();
  return {
    addHistogramSeries: vi.fn(() => {
      const series = createHistogramSeries();
      createdHistogramSeries.push(series);
      return series;
    }),
    addLineSeries: vi.fn(() => {
      const series = createLineSeries();
      createdLineSeries.push(series);
      return series;
    }),
    createdHistogramSeries,
    createdLineSeries,
    reset: () => {
      createdHistogramSeries.splice(0);
      createdLineSeries.splice(0);
    },
    volumeSeries,
  };
});

const paneRuntimeMocks = vi.hoisted(() => {
  const panes: Array<{ paneIndex: () => number; setStretchFactor: ReturnType<typeof vi.fn> }> = [
    { paneIndex: () => 0, setStretchFactor: vi.fn() },
  ];
  return {
    addPane: vi.fn(() => {
      const pane = { paneIndex: () => panes.length, setStretchFactor: vi.fn() };
      panes.push(pane);
      return pane;
    }),
    panes,
    reset: () => {
      panes.splice(1);
      panes[0].setStretchFactor.mockClear();
    },
  };
});

const priceScale = {
  applyOptions: vi.fn(),
};

const chart = {
  addPane: paneRuntimeMocks.addPane,
  addSeries: vi.fn(() => indicatorRuntimeMocks.createdLineSeries[0] ?? indicatorRuntimeMocks.volumeSeries),
  panes: vi.fn(() => paneRuntimeMocks.panes),
  priceScale: vi.fn(() => priceScale),
  removeSeries: vi.fn(),
};

vi.mock("lightweight-charts", () => ({
  HistogramSeries: Symbol("HistogramSeries"),
  LineSeries: Symbol("LineSeries"),
}));

vi.mock("@/lib/lightweightChartRuntime", () => ({
  lightweightHistogramRuntime: {
    addHistogramSeries: indicatorRuntimeMocks.addHistogramSeries,
  },
  lightweightLineRuntime: {
    addLineSeries: indicatorRuntimeMocks.addLineSeries,
  },
}));

const bars: OhlcvBar[] = Array.from({ length: 40 }, (_, index) => ({
  close: 22000 + index * 8,
  high: 22020 + index * 8,
  low: 21980 + index * 8,
  open: 21990 + index * 8,
  timestamp: index + 1,
  volume: 1000 + index * 25,
}));

const times = bars.map((bar) => bar.timestamp as Time);

function createIndicatorRefs(): IndicatorSeriesRefs {
  return {
    adx: null,
    adxMinus: null,
    adxPlus: null,
    atr: null,
    bbLower: null,
    bbMiddle: null,
    bbUpper: null,
    cci: null,
    dema: null,
    ema20: null,
    ema50: null,
    hullMA: null,
    ichChikou: null,
    ichKijun: null,
    ichSenkouA: null,
    ichSenkouB: null,
    ichTenkan: null,
    keltnerLower: null,
    keltnerMiddle: null,
    keltnerUpper: null,
    macdHist: null,
    macdLine: null,
    macdSignal: null,
    obv: null,
    parSar: null,
    rsi: null,
    sma: null,
    stDown: null,
    stUp: null,
    stochD: null,
    stochK: null,
    vwap: null,
    vwma: null,
    williamsR: null,
    wma: null,
  };
}

interface IndicatorsHarnessProps {
  indicators?: IndicatorState;
}

function IndicatorsHarness({ indicators }: IndicatorsHarnessProps = {}) {
  const chartRef = useRef(chart as unknown as IChartApi | null) as MutableRefObject<IChartApi | null>;
  const candleRef = useRef(null) as MutableRefObject<ISeriesApi<"Candlestick"> | null>;
  const volumeRef = useRef(
    indicatorRuntimeMocks.volumeSeries as unknown as ISeriesApi<"Histogram"> | null,
  ) as MutableRefObject<ISeriesApi<"Histogram"> | null>;
  const indRef = useRef(createIndicatorRefs());
  const barsRef = useRef(bars);
  const timesRef = useRef(times);

  useIndicators({
    barsRef,
    candleRef,
    chartRef,
    indRef,
    indicatorColors: FLINT_CHART_INDICATOR_DEFAULT_COLORS,
    indicatorLineStyles: FLINT_CHART_INDICATOR_DEFAULT_LINE_STYLES,
    indicatorPaneSizes: {
      ...FLINT_CHART_INDICATOR_DEFAULT_PANE_SIZES,
      macd: "expanded",
    },
    indicatorPaneStretchFactors: {
      ...FLINT_CHART_INDICATOR_DEFAULT_PANE_STRETCH_FACTORS,
      macd: 1.5,
    },
    indicators: indicators ?? {
      ...FLINT_CHART_DEFAULT_INDICATORS,
      showEMA20: true,
      showMACD: true,
    },
    periods: FLINT_CHART_DEFAULT_PERIODS,
    timesRef,
    volumeRef,
  });

  return null;
}

describe("useIndicators", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    indicatorRuntimeMocks.reset();
    paneRuntimeMocks.reset();
  });

  it("creates line and histogram indicator series through the shared Flint chart runtimes", async () => {
    render(<IndicatorsHarness />);

    await waitFor(() => {
      expect(lightweightLineRuntime.addLineSeries).toHaveBeenCalledWith(
        chart,
        expect.objectContaining({
          priceScaleId: "right",
          title: "EMA20",
        }),
        undefined,
      );
      expect(lightweightHistogramRuntime.addHistogramSeries).toHaveBeenCalledWith(
        chart,
        expect.objectContaining({
          priceScaleId: "macd",
          title: "MACD Hist",
        }),
        1,
      );
    });

    expect(lightweightLineRuntime.addLineSeries).toHaveBeenCalledTimes(3);
    expect(lightweightHistogramRuntime.addHistogramSeries).toHaveBeenCalledTimes(1);
    expect(paneRuntimeMocks.addPane).toHaveBeenCalledWith(true);
    expect(paneRuntimeMocks.panes[0].setStretchFactor).toHaveBeenCalledWith(4);
    expect(paneRuntimeMocks.panes[1].setStretchFactor).toHaveBeenCalledWith(1.5);
    expect(chart.priceScale).toHaveBeenCalledWith("macd", 1);
    expect(chart.addSeries).not.toHaveBeenCalled();
  });

  it("recreates indicator series whose core render-plan pane changes", async () => {
    const initialIndicators: IndicatorState = {
      ...FLINT_CHART_DEFAULT_INDICATORS,
      showMACD: true,
      showRSI: true,
    };
    const nextIndicators: IndicatorState = {
      ...FLINT_CHART_DEFAULT_INDICATORS,
      showMACD: true,
    };

    const { rerender } = render(<IndicatorsHarness indicators={initialIndicators} />);

    await waitFor(() => {
      expect(lightweightLineRuntime.addLineSeries).toHaveBeenCalledTimes(3);
      expect(lightweightHistogramRuntime.addHistogramSeries).toHaveBeenCalledTimes(1);
    });

    const initialLineSeries = [...indicatorRuntimeMocks.createdLineSeries];
    const initialHistogramSeries = [...indicatorRuntimeMocks.createdHistogramSeries];

    rerender(<IndicatorsHarness indicators={nextIndicators} />);

    await waitFor(() => {
      expect(chart.removeSeries).toHaveBeenCalledWith(initialLineSeries[0]);
      expect(chart.removeSeries).toHaveBeenCalledWith(initialLineSeries[1]);
      expect(chart.removeSeries).toHaveBeenCalledWith(initialLineSeries[2]);
      expect(chart.removeSeries).toHaveBeenCalledWith(initialHistogramSeries[0]);
      expect(lightweightLineRuntime.addLineSeries).toHaveBeenCalledTimes(5);
      expect(lightweightHistogramRuntime.addHistogramSeries).toHaveBeenCalledTimes(2);
    });
  });
});
