/**
 * StraddleWidget.test.tsx
 *
 * Tests for the Straddle analysis widget.
 * Verifies rendering, loading states, and key UI elements.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

const chartMocks = vi.hoisted(() => {
  const lineSeriesOptions: unknown[] = [];
  const localSeriesOptions: unknown[] = [];
  const createdLineSeries: Array<{
    setData: ReturnType<typeof vi.fn>;
    applyOptions: ReturnType<typeof vi.fn>;
  }> = [];

  const createSeries = () => ({
    setData: vi.fn(),
    applyOptions: vi.fn(),
  });

  const chart = {
    addSeries: vi.fn((_seriesType: unknown, options: unknown) => {
      localSeriesOptions.push(options);
      return createSeries();
    }),
    applyOptions: vi.fn(),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    remove: vi.fn(),
  };

  const shellRuntime = {
    createChart: vi.fn(() => chart),
  };

  const lineRuntime = {
    createChart: shellRuntime.createChart,
    addLineSeries: vi.fn((_chart: unknown, options: unknown) => {
      lineSeriesOptions.push(options);
      const series = createSeries();
      createdLineSeries.push(series);
      return series;
    }),
  };

  return {
    chart,
    shellRuntime,
    lineRuntime,
    lineSeriesOptions,
    localSeriesOptions,
    createdLineSeries,
    reset() {
      lineSeriesOptions.length = 0;
      localSeriesOptions.length = 0;
      createdLineSeries.length = 0;
    },
  };
});

const apiMocks = vi.hoisted(() => ({
  getExpiry: vi.fn(),
  getOptionChain: vi.fn(),
  getQuotes: vi.fn(),
  getPositionbook: vi.fn(),
}));

// Mock API calls used by the widget
vi.mock("@/services/api", () => ({
  getExpiry: apiMocks.getExpiry,
  getOptionChain: apiMocks.getOptionChain,
  getQuotes: apiMocks.getQuotes,
  getPositionbook: apiMocks.getPositionbook,
}));

// Mock market hours helper
vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

// Mock lightweight-charts to avoid canvas issues in JSDOM
vi.mock("lightweight-charts", () => ({
  createChart: chartMocks.shellRuntime.createChart,
  LineSeries: "LineSeries",
}));

vi.mock("@/lib/lightweightChartRuntime", () => ({
  lightweightChartShellRuntime: chartMocks.shellRuntime,
  lightweightLineRuntime: chartMocks.lineRuntime,
}));

// Mock chart theme hook
vi.mock("@/hooks/useChartTheme", () => ({
  useLightweightChartTheme: () => ({
    layout: {},
    grid: {},
    rightPriceScale: {},
    timeScale: {},
    // createFlintLineChart (real, from the design-system) reads
    // theme.crosshair.vertLine — the mock must carry the same shape.
    crosshair: { vertLine: {}, horzLine: {} },
  }),
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import StraddleWidget from "../StraddleWidget";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("StraddleWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    chartMocks.reset();
    apiMocks.getExpiry.mockResolvedValue([]);
    apiMocks.getOptionChain.mockResolvedValue({ calls: [], puts: [] });
    apiMocks.getQuotes.mockResolvedValue({ ltp: 0 });
    apiMocks.getPositionbook.mockResolvedValue([]);
  });

  it("renders without crashing", () => {
    const { container } = render(<StraddleWidget />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows the default symbol (NIFTY) in the selector", () => {
    render(<StraddleWidget />);
    expect(screen.getByText("NIFTY")).toBeInTheDocument();
  });

  it("shows headline price labels (Straddle, CE, PE)", () => {
    render(<StraddleWidget />);
    // "Straddle" appears in both headline and overlay toggle — use getAllByText
    const straddleElements = screen.getAllByText("Straddle");
    expect(straddleElements.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("CE")).toBeInTheDocument();
    expect(screen.getByText("PE")).toBeInTheDocument();
  });

  it("shows overlay toggle buttons", () => {
    render(<StraddleWidget />);
    expect(screen.getByText("Overlay")).toBeInTheDocument();
    expect(screen.getByText("Spot")).toBeInTheDocument();
    expect(screen.getByText("SynFut")).toBeInTheDocument();
  });

  it("routes overlay line series through the shared Flint line runtime", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-06-25"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 22510, prev_close: 22480 });
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 22500,
      calls: [{ strike_price: 22500, ltp: 112.5 }],
      puts: [{ strike_price: 22500, ltp: 98.25 }],
    });

    render(<StraddleWidget />);

    await waitFor(() => {
      expect(chartMocks.lineRuntime.addLineSeries).toHaveBeenCalledTimes(3);
    });
    expect(chartMocks.chart.addSeries).not.toHaveBeenCalled();
    expect(chartMocks.lineSeriesOptions).toEqual([
      expect.objectContaining({
        color: "#3b82f6",
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
      }),
      expect.objectContaining({
        color: "#eab308",
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        visible: false,
      }),
      expect.objectContaining({
        color: "#a78bfa",
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        visible: false,
      }),
    ]);
  });
});
