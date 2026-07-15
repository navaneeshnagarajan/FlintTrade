/**
 * PnLDashboardTool.test.tsx
 *
 * Tests for the P&L Dashboard canvas tool.
 * Verifies rendering, heading, tabs, and key UI elements.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

const mockUseModeData = vi.fn();
const chartRuntimeMocks = vi.hoisted(() => {
  const chart = {
    applyOptions: vi.fn(),
    remove: vi.fn(),
  };
  const areaSeries = {
    applyOptions: vi.fn(),
    setData: vi.fn(),
  };
  return {
    addAreaSeries: vi.fn(() => areaSeries),
    areaSeries,
    chart,
    createChart: vi.fn((container: HTMLElement) => {
      container.appendChild(document.createElement("canvas"));
      return chart;
    }),
  };
});

vi.mock("@/hooks/useModeData", () => ({
  useModeData: (...args: unknown[]) => mockUseModeData(...args),
}));

vi.mock("@/hooks/useChartTheme", () => ({
  useLightweightChartTheme: () => ({
    crosshair: {},
    grid: {},
    handleScale: {},
    handleScroll: {},
    kineticScroll: {},
    layout: { background: { color: "#020617", type: "solid" }, textColor: "#e5e7eb" },
    rightPriceScale: {},
    timeScale: {},
    trackingMode: {},
  }),
}));

vi.mock("@/lib/lightweightChartRuntime", () => ({
  lightweightAreaRuntime: {
    addAreaSeries: chartRuntimeMocks.addAreaSeries,
    createChart: chartRuntimeMocks.createChart,
  },
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import PnLDashboardTool from "../PnLDashboardTool";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function queryResult(overrides = {}) {
  return {
    data: undefined,
    isLoading: false,
    isPending: false,
    isError: false,
    error: null,
    isFetching: false,
    refetch: vi.fn(),
    dataUpdatedAt: 0,
    ...overrides,
  };
}

function setupMocks(config: {
  positions?: unknown[];
  posLoading?: boolean;
  posError?: boolean;
  funds?: Record<string, unknown>;
  fundsLoading?: boolean;
  trades?: unknown[];
  tradesLoading?: boolean;
} = {}) {
  mockUseModeData.mockImplementation((key: string) => {
    if (key === "positions") {
      return queryResult({
        data: config.positions ?? [],
        isLoading: config.posLoading ?? false,
        error: config.posError ? new Error("Position data unavailable") : null,
      });
    }
    if (key === "funds") {
      return queryResult({ data: config.funds, isLoading: config.fundsLoading ?? false });
    }
    return queryResult({ data: config.trades ?? [], isLoading: config.tradesLoading ?? false });
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PnLDashboardTool", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    chartRuntimeMocks.addAreaSeries.mockClear();
    chartRuntimeMocks.areaSeries.applyOptions.mockClear();
    chartRuntimeMocks.areaSeries.setData.mockClear();
    chartRuntimeMocks.chart.applyOptions.mockClear();
    chartRuntimeMocks.chart.remove.mockClear();
    chartRuntimeMocks.createChart.mockClear();
    setupMocks();
  });

  it("renders without crashing", () => {
    const { container } = render(<PnLDashboardTool />);
    expect(container).toBeInTheDocument();
  });

  it("shows the P&L Dashboard heading", () => {
    render(<PnLDashboardTool />);
    expect(screen.getByText("P&L Dashboard")).toBeInTheDocument();
  });

  it("has Summary, Calendar, and Drawdown tabs", () => {
    render(<PnLDashboardTool />);
    expect(screen.getByText("Summary")).toBeInTheDocument();
    expect(screen.getByText("Calendar")).toBeInTheDocument();
    expect(screen.getByText("Drawdown")).toBeInTheDocument();
  });

  it("renders the summary breakdown through shared core donut and ranked bar primitives", () => {
    setupMocks({
      positions: [
        {
          averagePrice: 2400,
          ltp: 2550,
          pnl: 1500,
          pnlPercent: 6.25,
          product: "MIS",
          quantity: 10,
          symbol: "RELIANCE",
        },
        {
          averagePrice: 3800,
          ltp: 3720,
          pnl: -800,
          pnlPercent: -2.1,
          product: "CNC",
          quantity: 10,
          symbol: "TCS",
        },
      ],
    });

    render(<PnLDashboardTool />);

    expect(screen.getByRole("img", { name: "P&L breakdown by symbol" })).toHaveAttribute(
      "data-flint-chart",
      "donut",
    );
    expect(screen.getByRole("list", { name: "Top winners P&L" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Top losers P&L" })).toBeInTheDocument();
  });

  it("renders drawdown charts through the shared Flint area runtime", async () => {
    setupMocks({
      trades: [
        {
          action: "BUY",
          exchange: "NSE",
          orderId: "o-1",
          price: 100,
          quantity: 10,
          symbol: "NIFTY",
          timestamp: "2026-05-29T09:30:00.000Z",
          tradeId: "t-1",
        },
        {
          action: "SELL",
          exchange: "NSE",
          orderId: "o-2",
          price: 120,
          quantity: 10,
          symbol: "NIFTY",
          timestamp: "2026-05-29T15:00:00.000Z",
          tradeId: "t-2",
        },
        {
          action: "BUY",
          exchange: "NSE",
          orderId: "o-3",
          price: 120,
          quantity: 10,
          symbol: "BANKNIFTY",
          timestamp: "2026-05-30T09:30:00.000Z",
          tradeId: "t-3",
        },
        {
          action: "SELL",
          exchange: "NSE",
          orderId: "o-4",
          price: 110,
          quantity: 10,
          symbol: "BANKNIFTY",
          timestamp: "2026-05-30T15:00:00.000Z",
          tradeId: "t-4",
        },
      ],
    });

    render(<PnLDashboardTool />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: /Drawdown/i }));

    await waitFor(() => {
      expect(chartRuntimeMocks.addAreaSeries).toHaveBeenCalledTimes(2);
    });

    expect(screen.getByRole("img", { name: "P&L dashboard equity curve chart" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "P&L dashboard drawdown chart" })).toBeInTheDocument();
    expect(chartRuntimeMocks.areaSeries.setData).toHaveBeenCalledWith([
      { time: "2026-05-29", value: 200 },
      { time: "2026-05-30", value: 100 },
    ]);
    expect(chartRuntimeMocks.areaSeries.setData).toHaveBeenCalledWith([
      { time: "2026-05-29", value: 0 },
      { time: "2026-05-30", value: -50 },
    ]);
  });
});
