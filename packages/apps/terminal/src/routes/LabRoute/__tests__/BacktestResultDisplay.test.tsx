import { render } from "@testing-library/react";
import "@testing-library/jest-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { BacktestResult } from "@/services/ftApi";

const chartMocks = vi.hoisted(() => {
  const areaSeriesOptions: unknown[] = [];
  const histogramSeriesOptions: unknown[] = [];
  const localSeriesOptions: unknown[] = [];
  const setData = vi.fn();
  const fitContent = vi.fn();

  const createSeries = () => ({
    applyOptions: vi.fn(),
    setData,
  });

  const chart = {
    addSeries: vi.fn((_seriesType: unknown, options: unknown) => {
      localSeriesOptions.push(options);
      return createSeries();
    }),
    applyOptions: vi.fn(),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    remove: vi.fn(),
    resize: vi.fn(),
    timeScale: vi.fn(() => ({ fitContent })),
  };

  const shellRuntime = {
    createChart: vi.fn(() => chart),
  };

  const areaRuntime = {
    createChart: shellRuntime.createChart,
    addAreaSeries: vi.fn((_chart: unknown, options: unknown) => {
      areaSeriesOptions.push(options);
      return createSeries();
    }),
  };

  const histogramRuntime = {
    createChart: shellRuntime.createChart,
    addHistogramSeries: vi.fn((_chart: unknown, options: unknown) => {
      histogramSeriesOptions.push(options);
      return createSeries();
    }),
  };

  return {
    areaRuntime,
    areaSeriesOptions,
    chart,
    fitContent,
    histogramRuntime,
    histogramSeriesOptions,
    localSeriesOptions,
    setData,
    reset() {
      areaSeriesOptions.length = 0;
      histogramSeriesOptions.length = 0;
      localSeriesOptions.length = 0;
      setData.mockClear();
      fitContent.mockClear();
    },
  };
});

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _initial, animate: _animate, transition: _transition, ...rest } = props;
      return <div {...rest}>{children as React.ReactNode}</div>;
    },
  },
}));

vi.mock("@/components/magicui/animated-counter", () => ({
  AnimatedCounter: ({ value }: { value: number }) => <span>{value}</span>,
}));

vi.mock("@/lib/lightweightChartRuntime", () => ({
  lightweightAreaRuntime: chartMocks.areaRuntime,
  lightweightHistogramRuntime: chartMocks.histogramRuntime,
}));

vi.mock("@/hooks/useChartTheme", () => ({
  useLightweightChartTheme: () => ({
    layout: {},
    grid: {},
    crosshair: {},
    rightPriceScale: {},
    timeScale: {},
    handleScale: false,
    handleScroll: false,
    kineticScroll: {},
    trackingMode: {},
  }),
}));

import { BacktestResultDisplay } from "../BacktestResultDisplay";

const result: BacktestResult = {
  final_equity: 104500,
  total_bars: 300,
  metrics: {
    total_return: 0.045,
    sharpe_ratio: 1.8,
    sortino_ratio: 2.1,
    max_drawdown: -0.02,
    win_rate: 0.66,
    profit_factor: 2.4,
    total_trades: 3,
    expectancy: 1500,
  },
  equity_curve: [
    { timestamp: "2024-01-01T00:00:00.000Z", equity: 100000 },
    { timestamp: "2024-02-01T00:00:00.000Z", equity: 102000 },
    { timestamp: "2024-03-01T00:00:00.000Z", equity: 104500 },
  ],
  trades: [
    {
      entry_timestamp: "2024-01-02T09:15:00.000Z",
      exit_timestamp: "2024-01-05T15:30:00.000Z",
      symbol: "NIFTY",
      side: "BUY",
      quantity: 20,
      entry_price: 22000,
      exit_price: 22100,
      pnl: 2000,
      commission: 40,
      bars_held: 75,
    },
    {
      entry_timestamp: "2024-02-02T09:15:00.000Z",
      exit_timestamp: "2024-02-05T15:30:00.000Z",
      symbol: "NIFTY",
      side: "SELL",
      quantity: 20,
      entry_price: 22300,
      exit_price: 22250,
      pnl: 1000,
      commission: 40,
      bars_held: 80,
    },
    {
      entry_timestamp: "2024-03-02T09:15:00.000Z",
      exit_timestamp: "2024-03-05T15:30:00.000Z",
      symbol: "NIFTY",
      side: "BUY",
      quantity: 20,
      entry_price: 22400,
      exit_price: 22325,
      pnl: -1500,
      commission: 40,
      bars_held: 70,
    },
  ],
};

describe("BacktestResultDisplay", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    chartMocks.reset();
  });

  it("routes the visible monthly P&L chart through the shared Flint histogram runtime", () => {
    render(<BacktestResultDisplay result={result} />);

    expect(chartMocks.histogramRuntime.addHistogramSeries).toHaveBeenCalledTimes(1);
    expect(chartMocks.chart.addSeries).not.toHaveBeenCalled();
    expect(chartMocks.histogramSeriesOptions).toEqual([
      expect.objectContaining({
        color: "#34d399",
        priceFormat: { type: "price", precision: 0, minMove: 1 },
        priceScaleId: "right",
      }),
    ]);
    expect(chartMocks.setData).toHaveBeenCalledWith([
      { color: "#34d399", time: 1704067200, value: 2000 },
      { color: "#34d399", time: 1706745600, value: 1000 },
      { color: "#f87171", time: 1709251200, value: -1500 },
    ]);
    expect(chartMocks.fitContent).toHaveBeenCalled();
  });
});
