/**
 * PositionHeatMapWidget.test.tsx
 *
 * Tests for the Position Heat Map trading widget.
 * Covers: crash-free render, empty state, position rectangles from mock data.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";

// ---------------------------------------------------------------------------
// Stubs — must be defined before any component import
// ---------------------------------------------------------------------------

// ResizeObserver is unavailable in JSDOM
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

// Mock usePositions — controlled per test
const mockUsePositions = vi.fn();

vi.mock("@/hooks/usePositions", () => ({
  usePositions: (...args: unknown[]) => mockUsePositions(...args),
}));

// useTrackBehavior — no side-effects needed in tests
vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

// modeStore — default to "live" so explore sample data is NOT shown
// (lets us test real data path clearly; we also test explore mode separately)
const mockModeStore = vi.fn();

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) =>
    mockModeStore(selector),
}));

// colourScale — return a deterministic colour string so assertions don't rely
// on exact RGB maths
vi.mock("@/lib/colourScale", () => ({
  divergingColourScaleRange: () => "rgb(80,160,100)",
  divergingColourScale: () => "rgb(80,160,100)",
}));

// tradingStore side-effect from usePositions (not called directly but
// imported transitively in the real hook; mock to be safe)
vi.mock("@/stores/tradingStore", () => ({
  useTradingStore: Object.assign(() => ({}), {
    getState: () => ({ updateFromPositions: vi.fn() }),
  }),
}));

// ---------------------------------------------------------------------------
// Component under test (imported after mocks)
// ---------------------------------------------------------------------------

import PositionHeatMapWidget from "../PositionHeatMapWidget";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = makeDockviewPanelProps();

function makeQueryResult(overrides: Record<string, unknown> = {}) {
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

/** Return "live" mode (disables explore sample data). */
function liveModeSelector(selector: (s: { mode: string }) => unknown) {
  return selector({ mode: "live" });
}

/** Return "explore" mode (shows explore sample data). */
function exploreModeSelector(selector: (s: { mode: string }) => unknown) {
  return selector({ mode: "explore" });
}

// Sample positions
const MOCK_POSITIONS = [
  {
    symbol: "INFY",
    exchange: "NSE",
    product: "CNC",
    quantity: 100,
    averagePrice: 1480,
    ltp: 1510,
    pnl: 3000,
    pnlPercent: 2.0,
  },
  {
    symbol: "TCS",
    exchange: "NSE",
    product: "CNC",
    quantity: 50,
    averagePrice: 3900,
    ltp: 3820,
    pnl: -4000,
    pnlPercent: -2.1,
  },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PositionHeatMapWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // Default: live mode, empty positions
    mockModeStore.mockImplementation(liveModeSelector);
    mockUsePositions.mockReturnValue(makeQueryResult({ data: [] }));
  });

  it("renders without crashing", () => {
    const { container } = render(<PositionHeatMapWidget {...defaultProps} />);
    expect(
      container.querySelector("[data-tour-target='positionheatmap']"),
    ).toBeInTheDocument();
  });

  it("shows 'No positions' empty state when there are no positions", () => {
    mockUsePositions.mockReturnValue(makeQueryResult({ data: [] }));
    render(<PositionHeatMapWidget {...defaultProps} />);

    expect(screen.getByText("No positions")).toBeInTheDocument();
  });

  it("shows empty state when data is undefined", () => {
    mockUsePositions.mockReturnValue(makeQueryResult({ data: undefined }));
    render(<PositionHeatMapWidget {...defaultProps} />);

    expect(screen.getByText("No positions")).toBeInTheDocument();
  });

  it("renders the widget header with title", () => {
    mockUsePositions.mockReturnValue(makeQueryResult({ data: [] }));
    render(<PositionHeatMapWidget {...defaultProps} />);

    // Header contains the widget name (partial text match)
    expect(screen.getByText(/Position Heat Map/i)).toBeInTheDocument();
  });

  it("renders position rectangles from mock data (does not show empty state)", () => {
    mockUsePositions.mockReturnValue(makeQueryResult({ data: MOCK_POSITIONS }));
    render(<PositionHeatMapWidget {...defaultProps} />);

    // With real positions loaded, the "No positions" empty state must be absent
    expect(screen.queryByText("No positions")).not.toBeInTheDocument();

    // The header count confirms both positions were processed
    expect(screen.getByText(/Position Heat Map \(2\)/i)).toBeInTheDocument();
  });

  it("shows explore mode sample data watermark in explore mode", () => {
    mockModeStore.mockImplementation(exploreModeSelector);
    // usePositions still returns empty; explore mode fills with sample data
    mockUsePositions.mockReturnValue(makeQueryResult({ data: [] }));
    render(<PositionHeatMapWidget {...defaultProps} />);

    expect(
      screen.getByText(/Sample data — connect a broker/i),
    ).toBeInTheDocument();
  });

  it("shows the error banner when positions fetch fails in live mode", () => {
    mockUsePositions.mockReturnValue(
      makeQueryResult({
        data: undefined,
        isError: true,
        error: new Error("Network timeout"),
      }),
    );
    render(<PositionHeatMapWidget {...defaultProps} />);

    expect(screen.getByText(/Failed to load positions/i)).toBeInTheDocument();
    expect(screen.getByText(/Network timeout/i)).toBeInTheDocument();
  });

  it("does NOT show error banner in explore mode even if fetch errors", () => {
    mockModeStore.mockImplementation(exploreModeSelector);
    mockUsePositions.mockReturnValue(
      makeQueryResult({ data: undefined, isError: true, error: new Error("unreachable") }),
    );
    render(<PositionHeatMapWidget {...defaultProps} />);

    // Error banner should be absent — explore mode bypasses it
    expect(screen.queryByText(/Failed to load positions/i)).not.toBeInTheDocument();
  });

  it("renders total P&L in the header when positions have non-zero P&L", () => {
    mockUsePositions.mockReturnValue(makeQueryResult({ data: MOCK_POSITIONS }));
    render(<PositionHeatMapWidget {...defaultProps} />);

    // Total P&L = 3000 + (-4000) = -1000 → "-₹1,000"
    expect(screen.getByText("-₹1,000")).toBeInTheDocument();
  });

  it("renders group mode selector", () => {
    mockUsePositions.mockReturnValue(makeQueryResult({ data: [] }));
    render(<PositionHeatMapWidget {...defaultProps} />);

    const select = screen.getByRole("combobox");
    expect(select).toBeInTheDocument();
  });
});
