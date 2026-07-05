/**
 * MTMMonitorWidget.test.tsx
 *
 * Tests for the MTM Monitor widget — displays real-time P&L chart with
 * target/stoploss lines and stat cards.
 *
 * Lightweight Charts is mocked since it requires a DOM canvas.
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";
import { render, screen } from "@testing-library/react";
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

// Mock usePositions and useFunds
vi.mock("@/hooks/usePositions", () => ({
  usePositions: vi.fn(() => ({ data: undefined, isLoading: false, error: null, refetch: vi.fn() })),
}));

vi.mock("@/hooks/useFunds", () => ({
  useFunds: vi.fn(() => ({ data: undefined, isLoading: false, error: null, refetch: vi.fn() })),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(true),
}));

// Mock PnLSummary sub-component (it makes its own API call)
vi.mock("../PnLSummary", () => ({
  PnLSummary: () => <div data-testid="pnl-summary">PnL Summary</div>,
}));

// Mock settingsStore riskLimits
vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) =>
    selector({
      riskLimits: { mtmTarget: 10000, mtmStoploss: 5000, maxPositionLots: 100, maxOrdersPerMinute: 10 },
    }),
  ),
}));

import { usePositions } from "@/hooks/usePositions";
import { useFunds } from "@/hooks/useFunds";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import MTMMonitorWidget from "../MTMMonitorWidget";

const mockUsePositions = usePositions as ReturnType<typeof vi.fn>;
const mockUseFunds = useFunds as ReturnType<typeof vi.fn>;
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

describe("MTMMonitorWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    chartMocks.reset();
    mockUseBrokerConnected.mockReturnValue(true);
  });

  it("renders without crashing", () => {
    mockUsePositions.mockReturnValue({ data: undefined });
    const { container } = render(<MTMMonitorWidget {...makeDockviewPanelProps()} />, { wrapper });
    expect(container).toBeTruthy();
  });

  it("displays the MTM Monitor header", () => {
    mockUsePositions.mockReturnValue({ data: undefined });
    render(<MTMMonitorWidget {...makeDockviewPanelProps()} />, { wrapper });

    expect(screen.getByText("MTM Monitor")).toBeInTheDocument();
  });

  it("shows target and stoploss values in header", () => {
    mockUsePositions.mockReturnValue({ data: undefined });
    render(<MTMMonitorWidget {...makeDockviewPanelProps()} />, { wrapper });

    // The header shows "Target ₹10,000 / SL ₹5,000"
    // Header shows "Target ₹10,000 / SL ₹5,000" — use getAllByText since
    // "Target" and "SL" also appear in the chart legend
    const targetElements = screen.getAllByText(/target/i);
    expect(targetElements.length).toBeGreaterThanOrEqual(1);
    const slElements = screen.getAllByText(/sl/i);
    expect(slElements.length).toBeGreaterThanOrEqual(1);
  });

  it("renders stat cards for Current MTM, Max MTM, Min MTM, Max DD", () => {
    mockUsePositions.mockReturnValue({ data: [] });
    render(<MTMMonitorWidget {...makeDockviewPanelProps()} />, { wrapper });

    expect(screen.getByText("Current MTM")).toBeInTheDocument();
    expect(screen.getByText("Max MTM")).toBeInTheDocument();
    expect(screen.getByText("Min MTM")).toBeInTheDocument();
    expect(screen.getByText("Max DD")).toBeInTheDocument();
  });

  it("renders the PnLSummary sub-component", () => {
    mockUsePositions.mockReturnValue({ data: [] });
    render(<MTMMonitorWidget {...makeDockviewPanelProps()} />, { wrapper });

    expect(screen.getByTestId("pnl-summary")).toBeInTheDocument();
  });

  it("shows chart legend items", () => {
    mockUsePositions.mockReturnValue({ data: [] });
    render(<MTMMonitorWidget {...makeDockviewPanelProps()} />, { wrapper });

    expect(screen.getByText("MTM PnL")).toBeInTheDocument();
    expect(screen.getByText("Drawdown")).toBeInTheDocument();
  });

  it("routes MTM area series through the shared Flint area runtime", () => {
    mockUsePositions.mockReturnValue({
      data: [{ pnl: 1200 }, { pnl: -300 }],
    });
    render(<MTMMonitorWidget {...makeDockviewPanelProps()} />, { wrapper });

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

  it("does not poll live positions and funds while broker is disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);

    render(<MTMMonitorWidget {...makeDockviewPanelProps()} />, { wrapper });

    expect(mockUsePositions).toHaveBeenCalledWith({ enabled: false });
    expect(mockUseFunds).toHaveBeenCalledWith({ enabled: false });
    expect(screen.getByText("Broker required")).toBeInTheDocument();
  });
});
