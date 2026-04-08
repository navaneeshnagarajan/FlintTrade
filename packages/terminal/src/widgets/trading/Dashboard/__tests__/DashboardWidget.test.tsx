/**
 * DashboardWidget.test.tsx
 *
 * Tests for the Dashboard trading widget.
 * Verifies rendering, loading states, fund data display, and P&L summary.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

const mockUseFunds = vi.fn();
const mockUsePositions = vi.fn();
const mockUseOrders = vi.fn();

vi.mock("@/hooks/useFunds", () => ({
  useFunds: (...args: unknown[]) => mockUseFunds(...args),
}));

vi.mock("@/hooks/usePositions", () => ({
  usePositions: (...args: unknown[]) => mockUsePositions(...args),
}));

vi.mock("@/hooks/useOrders", () => ({
  useOrders: (...args: unknown[]) => mockUseOrders(...args),
}));

// Mock Jotai tickAtomFamily — returns null tick (no WS data in test)
vi.mock("@/atoms/marketAtoms", () => ({
  tickAtomFamily: () => null,
}));

vi.mock("jotai", () => ({
  useAtomValue: () => null,
  atom: (v: unknown) => v,
}));

// Mock Tremor charts to avoid canvas/SVG rendering issues in JSDOM
vi.mock("@tremor/react", () => ({
  SparkAreaChart: () => null,
  Tracker: () => null,
}));

// Mock tradingStore to avoid side-effects in useFunds/usePositions
vi.mock("@/stores/tradingStore", () => ({
  useTradingStore: Object.assign(() => ({}), {
    getState: () => ({ updateFromFunds: vi.fn(), updateFromPositions: vi.fn() }),
  }),
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import DashboardWidget from "../DashboardWidget";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Minimal props that satisfy WidgetProps (extends IDockviewPanelProps). */
const defaultProps = {} as Parameters<typeof DashboardWidget>[0];

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

/**
 * Sets up hook mocks to return different results.
 */
function setupMocks(config: {
  funds?: Record<string, unknown>;
  fundsPending?: boolean;
  positions?: unknown[];
  positionsPending?: boolean;
  orders?: unknown[];
  ordersPending?: boolean;
}) {
  mockUseFunds.mockReturnValue(
    queryResult({
      data: config.funds,
      isPending: config.fundsPending ?? false,
    }),
  );
  mockUsePositions.mockReturnValue(
    queryResult({
      data: config.positions ?? [],
      isPending: config.positionsPending ?? false,
    }),
  );
  mockUseOrders.mockReturnValue(
    queryResult({
      data: config.orders ?? [],
      isPending: config.ordersPending ?? false,
    }),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DashboardWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setupMocks({});
  });

  it("renders without crashing", () => {
    const { container } = render(<DashboardWidget {...defaultProps} />);
    expect(container.querySelector("[data-tour-target='dashboard']")).toBeInTheDocument();
  });

  it("shows loading skeletons when funds are pending", () => {
    setupMocks({ fundsPending: true });
    render(<DashboardWidget {...defaultProps} />);

    // The heading "Funds" should still be visible
    expect(screen.getByText("Funds")).toBeInTheDocument();
    // "Margin Used" label should be visible
    expect(screen.getByText("Margin Used")).toBeInTheDocument();
  });

  it("displays fund data when loaded", () => {
    setupMocks({
      funds: { availablecash: 250000, utiliseddebits: 48500 },
    });
    render(<DashboardWidget {...defaultProps} />);

    // Available cash formatted in INR (no decimals): 2,50,000
    expect(screen.getByText(/2,50,000/)).toBeInTheDocument();
    // Used margin: 48,500
    expect(screen.getByText(/48,500/)).toBeInTheDocument();
  });

  it("displays P&L summary from positions", () => {
    setupMocks({
      funds: { availablecash: 100000, utiliseddebits: 20000 },
      positions: [
        { symbol: "NIFTY", pnl: 1500, quantity: 50, average_price: 100, ltp: 130 },
        { symbol: "BANKNIFTY", pnl: -500, quantity: 30, average_price: 200, ltp: 183 },
      ],
    });
    render(<DashboardWidget {...defaultProps} />);

    // Total P&L = 1500 + (-500) = 1000 => +₹1,000
    expect(screen.getByText("Day P&L")).toBeInTheDocument();
    expect(screen.getByText(/1,000/)).toBeInTheDocument();
  });

  it("shows 'No open positions' when positions array is empty", () => {
    setupMocks({ positions: [] });
    render(<DashboardWidget {...defaultProps} />);

    expect(screen.getByText("No open positions")).toBeInTheDocument();
  });

  it("shows 'No orders today' when orders array is empty", () => {
    setupMocks({ orders: [] });
    render(<DashboardWidget {...defaultProps} />);

    expect(screen.getByText("No orders today")).toBeInTheDocument();
  });
});
