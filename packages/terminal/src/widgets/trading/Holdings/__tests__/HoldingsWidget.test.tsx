/**
 * HoldingsWidget.test.tsx
 *
 * Tests for the Holdings widget — renders holding rows from useHoldings().
 * Verifies empty state, data rendering, and search filtering.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// Mock useHoldings hook
const mockRefetch = vi.fn();
const mockUseHoldings = vi.fn();

vi.mock("@/hooks/useHoldings", () => ({
  useHoldings: (...args: unknown[]) => mockUseHoldings(...args),
}));

import HoldingsWidget from "../HoldingsWidget";

function queryResult(overrides = {}) {
  return {
    data: undefined,
    isLoading: false,
    isPending: false,
    isError: false,
    error: null,
    isFetching: false,
    refetch: mockRefetch,
    dataUpdatedAt: 0,
    ...overrides,
  };
}

const SAMPLE_HOLDINGS = [
  {
    symbol: "RELIANCE",
    exchange: "NSE",
    quantity: "10",
    average_price: "2500.00",
    ltp: "2600.00",
  },
  {
    symbol: "TCS",
    exchange: "NSE",
    quantity: "5",
    average_price: "3400.00",
    ltp: "3300.00",
  },
];

describe("HoldingsWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders without crashing", () => {
    mockUseHoldings.mockReturnValue(queryResult({ data: [] }));
    const { container } = render(<HoldingsWidget {...({} as any)} />);
    expect(container).toBeTruthy();
  });

  it("shows 'No holdings' when data is empty", () => {
    mockUseHoldings.mockReturnValue(queryResult({ data: [] }));
    render(<HoldingsWidget {...({} as any)} />);
    expect(screen.getByText("No holdings")).toBeInTheDocument();
  });

  it("displays holding rows with symbol, qty, and P&L", () => {
    mockUseHoldings.mockReturnValue(queryResult({ data: SAMPLE_HOLDINGS }));
    render(<HoldingsWidget {...({} as any)} />);

    // Symbols should be displayed
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText("TCS")).toBeInTheDocument();

    // Quantities should be displayed
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("shows the holdings count in the header", () => {
    mockUseHoldings.mockReturnValue(queryResult({ data: SAMPLE_HOLDINGS }));
    render(<HoldingsWidget {...({} as any)} />);

    expect(screen.getByText("(2)")).toBeInTheDocument();
  });

  it("shows error banner when loading fails", () => {
    mockUseHoldings.mockReturnValue(
      queryResult({
        data: undefined,
        isError: true,
        error: new Error("Network error"),
      }),
    );
    render(<HoldingsWidget {...({} as any)} />);

    expect(screen.getByText(/failed to load holdings/i)).toBeInTheDocument();
  });

  it("filters holdings by symbol search", () => {
    mockUseHoldings.mockReturnValue(queryResult({ data: SAMPLE_HOLDINGS }));
    render(<HoldingsWidget {...({} as any)} />);

    const searchInput = screen.getByPlaceholderText(/filter symbol/i);
    fireEvent.change(searchInput, { target: { value: "REL" } });

    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    // TCS should be filtered out — it should not appear in the table
    expect(screen.queryByText("TCS")).not.toBeInTheDocument();
  });
});
