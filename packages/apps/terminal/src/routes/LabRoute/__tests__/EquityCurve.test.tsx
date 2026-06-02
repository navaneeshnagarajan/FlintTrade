import { render } from "@testing-library/react";
import "@testing-library/jest-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const chartMocks = vi.hoisted(() => {
  const areaSeriesOptions: unknown[] = [];
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

  return {
    areaRuntime,
    areaSeriesOptions,
    chart,
    fitContent,
    localSeriesOptions,
    setData,
    reset() {
      areaSeriesOptions.length = 0;
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

vi.mock("@/lib/lightweightChartRuntime", () => ({
  lightweightAreaRuntime: chartMocks.areaRuntime,
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

import { EquityCurve } from "../EquityCurve";

describe("LabRoute EquityCurve", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    chartMocks.reset();
  });

  it("routes visible backtest equity curves through the shared Flint area runtime", () => {
    render(
      <EquityCurve
        initialEquity={100000}
        curve={[
          { timestamp: "2024-01-01T00:00:00.000Z", equity: 100000 },
          { timestamp: "2024-01-02T00:00:00.000Z", equity: 101250 },
          { timestamp: "2024-01-03T00:00:00.000Z", equity: 102100 },
        ]}
      />,
    );

    expect(chartMocks.areaRuntime.addAreaSeries).toHaveBeenCalledTimes(1);
    expect(chartMocks.chart.addSeries).not.toHaveBeenCalled();
    expect(chartMocks.areaSeriesOptions).toEqual([
      expect.objectContaining({
        lineColor: "#34d399",
        lineWidth: 2,
        priceScaleId: "right",
      }),
    ]);
    expect(chartMocks.setData).toHaveBeenCalledWith([
      { time: 1704067200, value: 100000 },
      { time: 1704153600, value: 101250 },
      { time: 1704240000, value: 102100 },
    ]);
    expect(chartMocks.fitContent).toHaveBeenCalled();
  });
});
