/**
 * PnLMonitorChart.test.tsx
 *
 * Chart/feed-behaviour suite for the merged P&L Monitor (dedup 2.10) — the
 * pins ported from the retired MTM Monitor: series routing through the shared
 * Flint area runtime, target/stop-loss price lines from the SHARED
 * settingsStore.riskLimits, staleness chip, and the error banner + retry.
 *
 * Hook-level mocks (unlike PnLMonitorWidget.test.tsx, which mocks the API
 * layer) so feed states like `dataUpdatedAt` can be driven directly.
 * Lightweight Charts is mocked since it requires a DOM canvas.
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const chartMocks = vi.hoisted(() => {
  const areaSeriesOptions: unknown[] = [];
  const localSeriesOptions: unknown[] = [];

  const createPriceLine = vi.fn(() => ({}));
  const removePriceLine = vi.fn();
  const setData = vi.fn();
  const applySeriesOptions = vi.fn();

  const createSeries = () => ({
    setData,
    applyOptions: applySeriesOptions,
    createPriceLine,
    removePriceLine,
  });

  const chart = {
    addSeries: vi.fn((_seriesType: unknown, options: unknown) => {
      localSeriesOptions.push(options);
      return createSeries();
    }),
    timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
    applyOptions: vi.fn(),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    remove: vi.fn(),
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
    createPriceLine,
    localSeriesOptions,
    shellRuntime,
    reset() {
      areaSeriesOptions.length = 0;
      localSeriesOptions.length = 0;
      createPriceLine.mockClear();
      removePriceLine.mockClear();
      setData.mockClear();
      applySeriesOptions.mockClear();
    },
  };
});

// Mock lightweight-charts (canvas-based, does not work in jsdom)
vi.mock("lightweight-charts", () => ({
  AreaSeries: {},
  ColorType: { Solid: "solid" },
  CrosshairMode: { Normal: 0 },
  createChart: chartMocks.shellRuntime.createChart,
}));

vi.mock("@/lib/lightweightChartRuntime", () => ({
  lightweightChartShellRuntime: chartMocks.shellRuntime,
  lightweightAreaRuntime: chartMocks.areaRuntime,
}));

// Mock the shared data hooks — one entry path per shape, driven per test.
vi.mock("@/hooks/usePositions", () => ({
  usePositions: vi.fn(() => ({ data: undefined, isLoading: false, error: null, refetch: vi.fn() })),
}));

vi.mock("@/hooks/useFunds", () => ({
  useFunds: vi.fn(() => ({ data: undefined, isLoading: false, error: null, refetch: vi.fn() })),
}));

vi.mock("@/hooks/useTradebook", () => ({
  useTradebook: vi.fn(() => ({ data: undefined, isLoading: false, error: null, refetch: vi.fn() })),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(true),
}));

const mockUseAccountReadsEnabled = vi.fn().mockReturnValue(true);
vi.mock("@/hooks/useAccountReadsEnabled", () => ({
  useAccountReadsEnabled: () => mockUseAccountReadsEnabled(),
}));

// Mock settingsStore riskLimits — the SHARED setting the price lines render.
vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) =>
    selector({
      riskLimits: { mtmTarget: 10000, mtmStoploss: 5000, maxPositionLots: 100, maxOrdersPerMinute: 10 },
    }),
  ),
}));

import { usePositions } from "@/hooks/usePositions";
import { useFunds } from "@/hooks/useFunds";
import { useTradebook } from "@/hooks/useTradebook";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import PnLMonitorWidget from "../PnLMonitorWidget";

const mockUsePositions = usePositions as ReturnType<typeof vi.fn>;
const mockUseFunds = useFunds as ReturnType<typeof vi.fn>;
const mockUseTradebook = useTradebook as ReturnType<typeof vi.fn>;
const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeAll(() => {
  // ResizeObserver is not available in jsdom
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("PnLMonitorWidget — chart and feed behaviour", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    chartMocks.reset();
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseAccountReadsEnabled.mockReturnValue(true);
    mockUseFunds.mockReturnValue({ data: undefined });
    mockUseTradebook.mockReturnValue({ data: undefined });
  });

  it("renders without crashing", () => {
    mockUsePositions.mockReturnValue({ data: undefined });
    const { container } = render(<PnLMonitorWidget {...makeWidgetPanelProps()} />, { wrapper });
    expect(container).toBeTruthy();
  });

  it("displays the P&L Monitor header", () => {
    mockUsePositions.mockReturnValue({ data: undefined });
    render(<PnLMonitorWidget {...makeWidgetPanelProps()} />, { wrapper });

    expect(screen.getByText("P&L Monitor")).toBeInTheDocument();
  });

  it("shows target and stoploss values in header", () => {
    mockUsePositions.mockReturnValue({ data: undefined });
    render(<PnLMonitorWidget {...makeWidgetPanelProps()} />, { wrapper });

    // Header shows "Target ₹10,000 / SL ₹5,000" — use getAllByText since
    // "Target" and "SL" also appear in the chart legend
    const targetElements = screen.getAllByText(/target/i);
    expect(targetElements.length).toBeGreaterThanOrEqual(1);
    const slElements = screen.getAllByText(/sl/i);
    expect(slElements.length).toBeGreaterThanOrEqual(1);
  });

  it("renders stat cards for Realised, Unrealised, Peak, Min and Max DD", () => {
    mockUsePositions.mockReturnValue({ data: [] });
    render(<PnLMonitorWidget {...makeWidgetPanelProps()} />, { wrapper });

    expect(screen.getByText("Realised")).toBeInTheDocument();
    expect(screen.getByText("Unrealised")).toBeInTheDocument();
    expect(screen.getByText("Peak P&L")).toBeInTheDocument();
    expect(screen.getByText("Min P&L")).toBeInTheDocument();
    expect(screen.getByText("Max DD")).toBeInTheDocument();
  });

  it("shows chart legend items", () => {
    mockUsePositions.mockReturnValue({ data: [] });
    render(<PnLMonitorWidget {...makeWidgetPanelProps()} />, { wrapper });

    expect(screen.getByText("Net P&L")).toBeInTheDocument();
    // "Drawdown" also names the view tab — the legend adds a second instance.
    expect(screen.getAllByText("Drawdown").length).toBeGreaterThanOrEqual(2);
  });

  it("routes the P&L area series through the shared Flint area runtime", () => {
    mockUsePositions.mockReturnValue({
      data: [{ pnl: 1200 }, { pnl: -300 }],
    });
    render(<PnLMonitorWidget {...makeWidgetPanelProps()} />, { wrapper });

    expect(chartMocks.areaRuntime.addAreaSeries).toHaveBeenCalledTimes(2);
    expect(chartMocks.chart.addSeries).not.toHaveBeenCalled();
    expect(chartMocks.areaSeriesOptions).toEqual([
      expect.objectContaining({
        lineColor: "#7C3AED",
        topColor: "rgba(124,58,237,0.35)",
        bottomColor: "rgba(124,58,237,0.02)",
        lineWidth: 2,
        priceScaleId: "right",
      }),
      expect.objectContaining({
        lineColor: "#EF4444",
        topColor: "rgba(239,68,68,0.0)",
        bottomColor: "rgba(239,68,68,0.25)",
        lineWidth: 1,
        priceScaleId: "right",
      }),
    ]);
  });

  it("draws target and stop-loss price lines from the shared risk limits", () => {
    mockUsePositions.mockReturnValue({ data: [] });
    render(<PnLMonitorWidget {...makeWidgetPanelProps()} />, { wrapper });

    expect(chartMocks.createPriceLine).toHaveBeenCalledWith(
      expect.objectContaining({ price: 10000, title: "Target" }),
    );
    expect(chartMocks.createPriceLine).toHaveBeenCalledWith(
      expect.objectContaining({ price: -5000, title: "SL" }),
    );
  });

  it("gates shared caches and shows Broker required (no Sample) when disconnected in Live", () => {
    // Per truthful provenance contract: disconnected Live (no sample pack bound) must not
    // fabricate Sample data or call prohibited account APIs. Shows honest Broker required.
    mockUseBrokerConnected.mockReturnValue(false);
    mockUseAccountReadsEnabled.mockReturnValue(false);
    mockUsePositions.mockReturnValue({ data: undefined });

    render(<PnLMonitorWidget {...makeWidgetPanelProps()} />, { wrapper });

    expect(mockUsePositions).toHaveBeenCalledWith({ enabled: false });
    expect(mockUseFunds).toHaveBeenCalledWith({ enabled: false });
    expect(mockUseTradebook).toHaveBeenCalledWith({ enabled: false });
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    expect(screen.getByText(/Broker required|Connect a broker to load/i)).toBeInTheDocument();
  });

  // ── Error honesty + staleness — a silently frozen P&L is a trading hazard ──

  it("shows an error banner with the server message and a retry when the feed fails", () => {
    const refetch = vi.fn();
    mockUsePositions.mockReturnValue({
      data: undefined,
      isError: true,
      error: new Error("positionbook 500"),
      refetch,
      isFetching: false,
      dataUpdatedAt: 0,
    });
    render(<PnLMonitorWidget {...makeWidgetPanelProps()} />, { wrapper });

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/position feed failed/i);
    expect(alert).toHaveTextContent("positionbook 500");

    fireEvent.click(screen.getByRole("button", { name: "Retry position fetch" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("stamps the failure banner with the time of the last good data", () => {
    mockUsePositions.mockReturnValue({
      data: [{ pnl: 100 }],
      isError: true,
      error: new Error("timeout"),
      refetch: vi.fn(),
      isFetching: false,
      dataUpdatedAt: Date.now(),
    });
    render(<PnLMonitorWidget {...makeWidgetPanelProps()} />, { wrapper });

    expect(screen.getByRole("alert")).toHaveTextContent(/frozen at \d{2}:\d{2}:\d{2}/i);
  });

  it("shows a last-updated indicator when live data is present", () => {
    mockUsePositions.mockReturnValue({ data: [], dataUpdatedAt: Date.now() });
    render(<PnLMonitorWidget {...makeWidgetPanelProps()} />, { wrapper });

    // Name-filtered: the sample-data badge is also a status region.
    const status = screen.getByRole("status", { name: /last updated/i });
    expect(status).toHaveTextContent(/updated \d{2}:\d{2}:\d{2}/i);
  });

  it("flags the last-updated indicator as stale when data stops refreshing", () => {
    mockUsePositions.mockReturnValue({ data: [], dataUpdatedAt: Date.now() - 10 * 60_000 });
    render(<PnLMonitorWidget {...makeWidgetPanelProps()} />, { wrapper });

    expect(screen.getByRole("status", { name: /last updated/i })).toHaveTextContent(/stale since/i);
  });

  it("suppresses the error banner and staleness chip while account reads are disabled", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockUseAccountReadsEnabled.mockReturnValue(false);
    mockUsePositions.mockReturnValue({
      data: undefined,
      isError: true,
      error: new Error("not polled"),
      dataUpdatedAt: Date.now(),
    });
    render(<PnLMonitorWidget {...makeWidgetPanelProps()} />, { wrapper });

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("status", { name: /last updated/i })).not.toBeInTheDocument();
    // The quiet header dot still reports the failure (IntradayPnL affordance).
    expect(document.querySelector(".bg-loss.rounded-full")).toBeInTheDocument();
  });
});
