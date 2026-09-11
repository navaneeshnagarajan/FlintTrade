import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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
import { fmtInr } from "../formatters";

/** Equity Δ is ₹4,500; trade-log sum is ₹1,500 — intentional diverge fixture. */
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
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <BacktestResultDisplay result={result} />
      </QueryClientProvider>,
    );

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

  it("shows one formatted value per headline metric, with no leftover 0.00", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <BacktestResultDisplay result={result} />
      </QueryClientProvider>,
    );

    const sharpe = (screen.getByText("Sharpe Ratio").parentElement?.textContent ?? "").replace(/\s+/g, " ").trim();
    const winRate = (screen.getByText("Win Rate").parentElement?.textContent ?? "").replace(/\s+/g, " ").trim();
    const profitFactor = (screen.getByText("Profit Factor").parentElement?.textContent ?? "").replace(/\s+/g, " ").trim();
    expect(sharpe).toMatch(/^Sharpe Ratio\s*1\.80$/);
    expect(winRate).toMatch(/^Win Rate\s*66\.00%$/);
    expect(profitFactor).toMatch(/^Profit Factor\s*2\.40$/);
    expect(sharpe).not.toMatch(/0\.00/);
    expect(winRate).not.toMatch(/0\.00%/);
    expect(profitFactor).not.toMatch(/0\.00/);
  });

  it("shows one value for the Explore sma_crossover demo figures", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const demoResult: BacktestResult = {
      ...result,
      metrics: {
        ...result.metrics,
        sharpe_ratio: 1.84,
        win_rate: 0.75,
        profit_factor: 8.43,
      },
    };
    render(
      <QueryClientProvider client={qc}>
        <BacktestResultDisplay result={demoResult} />
      </QueryClientProvider>,
    );

    const sharpe = (screen.getByText("Sharpe Ratio").parentElement?.textContent ?? "").replace(/\s+/g, " ").trim();
    const winRate = (screen.getByText("Win Rate").parentElement?.textContent ?? "").replace(/\s+/g, " ").trim();
    const profitFactor = (screen.getByText("Profit Factor").parentElement?.textContent ?? "").replace(/\s+/g, " ").trim();
    expect(sharpe).toMatch(/^Sharpe Ratio\s*1\.84$/);
    expect(winRate).toMatch(/^Win Rate\s*75\.00%$/);
    expect(profitFactor).toMatch(/^Profit Factor\s*8\.43$/);
    expect(sharpe).not.toMatch(/0\.00/);
    expect(winRate).not.toMatch(/0\.00%/);
    expect(profitFactor).not.toMatch(/0\.00/);
  });

  function renderResult(value: BacktestResult = result) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    return render(
      <QueryClientProvider client={qc}>
        <BacktestResultDisplay result={value} />
      </QueryClientProvider>,
    );
  }

  function metricCardText(label: string): string {
    const labelEl = screen.getByText(label);
    const card = labelEl.parentElement;
    expect(card).not.toBeNull();
    return (card?.textContent ?? "").replace(/\s+/g, " ").trim();
  }

  it("labels Total Return as equity-curve start→end, not a sum of trades", () => {
    renderResult();

    expect(metricCardText("Total Return")).toContain("4.50%");
    expect(screen.getByText("Equity curve · start→end")).toBeInTheDocument();
    expect(screen.queryByText(/sum of trades/i)).not.toBeInTheDocument();
  });

  it("adds Net trade P&L from the Trade Log and a diverge helper when it disagrees with equity Δ", () => {
    renderResult();

    expect(metricCardText("Net trade P&L")).toContain(fmtInr(1500));
    expect(
      screen.getByText("Trade log sum ≠ equity change — fees / open marks"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Reconciles with trade log")).not.toBeInTheDocument();
  });

  it("quietly notes when Net trade P&L matches the equity-curve change", () => {
    const reconciled: BacktestResult = {
      ...result,
      trades: [
        result.trades[0],
        result.trades[1],
        { ...result.trades[2], pnl: 1500 },
      ],
    };
    renderResult(reconciled);

    expect(metricCardText("Net trade P&L")).toContain(fmtInr(4500));
    expect(screen.getByText("Reconciles with trade log")).toBeInTheDocument();
    expect(
      screen.queryByText("Trade log sum ≠ equity change — fees / open marks"),
    ).not.toBeInTheDocument();
  });

  it("labels Monthly P&L as trade-based so the chart matches the Trade Log", () => {
    renderResult();

    expect(screen.getByText("Monthly P&L")).toBeInTheDocument();
    expect(screen.getByText("Trade-based · sums Trade Log P&L")).toBeInTheDocument();
  });

  it("omits the reconcile helper when there is no trade log or equity curve to compare", () => {
    const empty: BacktestResult = {
      ...result,
      trades: [],
      equity_curve: [],
      metrics: { ...result.metrics, total_trades: 0 },
    };
    renderResult(empty);

    expect(screen.getByText("Net trade P&L")).toBeInTheDocument();
    expect(screen.queryByText("Reconciles with trade log")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Trade log sum ≠ equity change — fees / open marks"),
    ).not.toBeInTheDocument();
  });
});
