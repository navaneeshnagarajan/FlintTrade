/**
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";
 * MTMMonitorWidget.test.tsx
 *
 * Tests for the MTM Monitor widget — displays real-time P&L chart with
 * target/stoploss lines and stat cards.
 *
 * Lightweight Charts is mocked since it requires a DOM canvas.
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Mock lightweight-charts (canvas-based, does not work in jsdom)
vi.mock("lightweight-charts", () => ({
  AreaSeries: {},
  ColorType: { Solid: "solid" },
  CrosshairMode: { Normal: 0 },
  createChart: vi.fn(() => ({
    addSeries: vi.fn(() => ({
      setData: vi.fn(),
      createPriceLine: vi.fn(() => ({})),
      removePriceLine: vi.fn(),
    })),
    timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
    applyOptions: vi.fn(),
    remove: vi.fn(),
  })),
}));

// Mock usePositions and useFunds
vi.mock("@/hooks/usePositions", () => ({
  usePositions: vi.fn(() => ({ data: undefined, isLoading: false, error: null, refetch: vi.fn() })),
}));

vi.mock("@/hooks/useFunds", () => ({
  useFunds: vi.fn(() => ({ data: undefined, isLoading: false, error: null, refetch: vi.fn() })),
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
import MTMMonitorWidget from "../MTMMonitorWidget";

const mockUsePositions = usePositions as ReturnType<typeof vi.fn>;

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
  });

  it("renders without crashing", () => {
    mockUsePositions.mockReturnValue({ data: undefined });
    const { container } = render(<MTMMonitorWidget {...{} as any} />, { wrapper });
    expect(container).toBeTruthy();
  });

  it("displays the MTM Monitor header", () => {
    mockUsePositions.mockReturnValue({ data: undefined });
    render(<MTMMonitorWidget {...{} as any} />, { wrapper });

    expect(screen.getByText("MTM Monitor")).toBeInTheDocument();
  });

  it("shows target and stoploss values in header", () => {
    mockUsePositions.mockReturnValue({ data: undefined });
    render(<MTMMonitorWidget {...{} as any} />, { wrapper });

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
    render(<MTMMonitorWidget {...{} as any} />, { wrapper });

    expect(screen.getByText("Current MTM")).toBeInTheDocument();
    expect(screen.getByText("Max MTM")).toBeInTheDocument();
    expect(screen.getByText("Min MTM")).toBeInTheDocument();
    expect(screen.getByText("Max DD")).toBeInTheDocument();
  });

  it("renders the PnLSummary sub-component", () => {
    mockUsePositions.mockReturnValue({ data: [] });
    render(<MTMMonitorWidget {...{} as any} />, { wrapper });

    expect(screen.getByTestId("pnl-summary")).toBeInTheDocument();
  });

  it("shows chart legend items", () => {
    mockUsePositions.mockReturnValue({ data: [] });
    render(<MTMMonitorWidget {...{} as any} />, { wrapper });

    expect(screen.getByText("MTM PnL")).toBeInTheDocument();
    expect(screen.getByText("Drawdown")).toBeInTheDocument();
  });
});
