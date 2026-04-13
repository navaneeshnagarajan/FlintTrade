/**
 * PositionsWidget.test.tsx
 *
 * Tests for the Positions trading widget.
 * Verifies rendering, empty state, and position row display.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockUsePositions = vi.fn();

vi.mock("@/hooks/usePositions", () => ({
  usePositions: (...args: unknown[]) => mockUsePositions(...args),
}));

// Mock tradingStore to avoid side-effects in usePositions
vi.mock("@/stores/tradingStore", () => ({
  useTradingStore: Object.assign(() => ({}), {
    getState: () => ({ updateFromPositions: vi.fn() }),
  }),
}));

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------

import PositionsWidget from "../PositionsWidget";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = {} as Parameters<typeof PositionsWidget>[0];

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

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PositionsWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockUsePositions.mockReturnValue(queryResult({ data: [] }));
  });

  it("renders without crashing", () => {
    const { container } = render(<PositionsWidget {...defaultProps} />);
    expect(container.querySelector("[data-tour-target='positions']")).toBeInTheDocument();
  });

  it("shows 'No open positions' when data is empty", () => {
    mockUsePositions.mockReturnValue(queryResult({ data: [] }));
    render(<PositionsWidget {...defaultProps} />);

    expect(screen.getByText("No open positions")).toBeInTheDocument();
  });

  it("displays position rows with symbol, qty, and P&L", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          { symbol: "NIFTY24APR24000CE", pnl: 1200, quantity: 75, ltp: 150, average_price: 134 },
          { symbol: "BANKNIFTY24APR51000PE", pnl: -800, quantity: -30, ltp: 220, average_price: 193 },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    // Symbols should be visible
    expect(screen.getByText("NIFTY24APR24000CE")).toBeInTheDocument();
    expect(screen.getByText("BANKNIFTY24APR51000PE")).toBeInTheDocument();

    // P&L values rendered via formatPnl: positive gets "+", negative gets just sign prefix
    expect(screen.getByText("+₹1,200")).toBeInTheDocument();
    // formatPnl(-800) produces "₹800" (Math.abs, no sign prefix for negative)
    expect(screen.getByText("₹800")).toBeInTheDocument();
  });

  it("shows the header with position count", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          { symbol: "NIFTY", pnl: 500, quantity: 50, ltp: 100, average_price: 90 },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    // Header shows "Positions (1)"
    expect(screen.getByText("Positions (1)")).toBeInTheDocument();
  });

  it("displays total P&L in the header", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          { symbol: "A", pnl: 1000, quantity: 10, ltp: 100, average_price: 90 },
          { symbol: "B", pnl: -300, quantity: 20, ltp: 50, average_price: 65 },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    // Total = 1000 + (-300) = 700 => P&L: +₹700
    expect(screen.getByText("P&L: +₹700")).toBeInTheDocument();
  });

  // ── Interaction tests ────────────────────────────────────────────────────

  it("shows error banner and Retry button when data fetch fails", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: undefined,
        isError: true,
        error: new Error("Network timeout"),
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    expect(screen.getByText(/failed to load positions/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("calls refetch when Retry button is clicked in error state", () => {
    const mockRefetch = vi.fn();
    mockUsePositions.mockReturnValue(
      queryResult({
        data: undefined,
        isError: true,
        error: new Error("Server error"),
        refetch: mockRefetch,
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    const retryBtn = screen.getByRole("button", { name: /retry/i });
    fireEvent.click(retryBtn);

    expect(mockRefetch).toHaveBeenCalledTimes(1);
  });

  it("clicking the Symbol column header toggles sort direction indicator", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          { symbol: "NIFTY", pnl: 500, quantity: 50, ltp: 100, average_price: 90 },
          { symbol: "BANKNIFTY", pnl: 200, quantity: 25, ltp: 200, average_price: 190 },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    const symbolHeader = screen.getByRole("columnheader", { name: /symbol/i });
    // First click — ascending sort indicator
    fireEvent.click(symbolHeader);
    expect(symbolHeader.textContent).toMatch(/symbol.*↑/i);

    // Second click — descending
    fireEvent.click(symbolHeader);
    expect(symbolHeader.textContent).toMatch(/symbol.*↓/i);
  });

  it("shows Retry button as disabled while isFetching is true", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: undefined,
        isError: true,
        error: new Error("Error"),
        isFetching: true,
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    const retryBtn = screen.getByRole("button", { name: /retrying/i });
    expect(retryBtn).toBeDisabled();
  });
});
