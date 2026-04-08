/**
 * OrdersWidget.test.tsx
 *
 * Tests for the Orders trading widget.
 * Verifies rendering, empty state, and order row display.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockUseOrders = vi.fn();

vi.mock("@/hooks/useOrders", () => ({
  useOrders: (...args: unknown[]) => mockUseOrders(...args),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------

import OrdersWidget from "../OrdersWidget";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = {} as Parameters<typeof OrdersWidget>[0];

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

describe("OrdersWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockUseOrders.mockReturnValue(queryResult({ data: [] }));
  });

  it("renders without crashing", () => {
    const { container } = render(<OrdersWidget {...defaultProps} />);
    expect(container).toBeTruthy();
  });

  it("shows 'No orders today' when data is empty", () => {
    mockUseOrders.mockReturnValue(queryResult({ data: [] }));
    render(<OrdersWidget {...defaultProps} />);

    expect(screen.getByText("No orders today")).toBeInTheDocument();
  });

  it("displays order rows with symbol, action, and status", () => {
    mockUseOrders.mockReturnValue(
      queryResult({
        data: [
          {
            symbol: "NIFTY24APR24000CE",
            action: "BUY",
            quantity: 75,
            price: 150,
            order_status: "complete",
          },
          {
            symbol: "BANKNIFTY24APR51000PE",
            action: "SELL",
            quantity: 30,
            price: 0,
            order_status: "rejected",
          },
        ],
      }),
    );
    render(<OrdersWidget {...defaultProps} />);

    // Symbols
    expect(screen.getByText("NIFTY24APR24000CE")).toBeInTheDocument();
    expect(screen.getByText("BANKNIFTY24APR51000PE")).toBeInTheDocument();

    // Actions
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("SELL")).toBeInTheDocument();

    // Statuses rendered in Badge components
    expect(screen.getByText("complete")).toBeInTheDocument();
    expect(screen.getByText("rejected")).toBeInTheDocument();
  });

  it("shows the header with order count", () => {
    mockUseOrders.mockReturnValue(
      queryResult({
        data: [
          { symbol: "NIFTY", action: "BUY", quantity: 50, order_status: "complete" },
        ],
      }),
    );
    render(<OrdersWidget {...defaultProps} />);

    expect(screen.getByText("Orders (1)")).toBeInTheDocument();
  });

  it("has a refresh button with correct aria-label", () => {
    render(<OrdersWidget {...defaultProps} />);

    expect(screen.getByLabelText("Refresh orders")).toBeInTheDocument();
  });
});
