/**
 * TradeBookWidget.test.tsx
 *
 * Tests for the TradeBook widget — renders trade rows from useTradebook().
 * Verifies empty state, data rendering, and BUY/SELL filter pills.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";

// Mock useTradebook hook
const mockRefetch = vi.fn();
const mockUseTradebook = vi.fn();
const mockUseBrokerConnected = vi.fn();

vi.mock("@/hooks/useTradebook", () => ({
  useTradebook: (...args: unknown[]) => mockUseTradebook(...args),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => mockUseBrokerConnected(),
}));

import TradeBookWidget from "../TradeBookWidget";

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

const SAMPLE_TRADES = [
  {
    symbol: "NIFTY24APR23000CE",
    action: "BUY",
    quantity: "50",
    average_price: "150.00",
    trade_time: "2026-04-08T10:30:00+05:30",
  },
  {
    symbol: "NIFTY24APR23000PE",
    action: "SELL",
    quantity: "25",
    average_price: "80.00",
    trade_time: "2026-04-08T10:35:00+05:30",
  },
  {
    symbol: "BANKNIFTY24APR50000CE",
    action: "BUY",
    quantity: "15",
    average_price: "200.00",
    trade_time: "2026-04-08T11:00:00+05:30",
  },
];

describe("TradeBookWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockUseBrokerConnected.mockReturnValue(true);
  });

  it("renders without crashing", () => {
    mockUseTradebook.mockReturnValue(queryResult({ data: [] }));
    const { container } = render(<TradeBookWidget {...makeDockviewPanelProps()} />);
    expect(container).toBeTruthy();
  });

  it("shows 'No trades today' when data is empty", () => {
    mockUseTradebook.mockReturnValue(queryResult({ data: [] }));
    render(<TradeBookWidget {...makeDockviewPanelProps()} />);
    expect(screen.getByText("No trades today")).toBeInTheDocument();
  });

  it("displays trade rows with symbol and side badges", () => {
    mockUseTradebook.mockReturnValue(queryResult({ data: SAMPLE_TRADES }));
    render(<TradeBookWidget {...makeDockviewPanelProps()} />);

    // Symbols should appear (uppercase)
    expect(screen.getByText("NIFTY24APR23000CE")).toBeInTheDocument();
    expect(screen.getByText("NIFTY24APR23000PE")).toBeInTheDocument();
    expect(screen.getByText("BANKNIFTY24APR50000CE")).toBeInTheDocument();

    // BUY and SELL badges
    expect(screen.getAllByText("BUY")).toHaveLength(2);
    expect(screen.getAllByText("SELL")).toHaveLength(1);
  });

  it("shows total trade count in the header", () => {
    mockUseTradebook.mockReturnValue(queryResult({ data: SAMPLE_TRADES }));
    render(<TradeBookWidget {...makeDockviewPanelProps()} />);

    expect(screen.getByText("(3)")).toBeInTheDocument();
  });

  it("filters trades by BUY/SELL pills", () => {
    mockUseTradebook.mockReturnValue(queryResult({ data: SAMPLE_TRADES }));
    render(<TradeBookWidget {...makeDockviewPanelProps()} />);

    // Click "Sell" filter pill
    const sellPill = screen.getByText(/^Sell/);
    fireEvent.click(sellPill);

    // Only the SELL trade should remain visible
    expect(screen.getByText("NIFTY24APR23000PE")).toBeInTheDocument();
    expect(screen.queryByText("NIFTY24APR23000CE")).not.toBeInTheDocument();
    expect(screen.queryByText("BANKNIFTY24APR50000CE")).not.toBeInTheDocument();
  });

  it("shows an error banner with Retry instead of 'No trades today' when the fetch fails", () => {
    mockUseTradebook.mockReturnValue(
      queryResult({ data: undefined, isError: true, error: new Error("OpenAlgo server error") }),
    );
    render(<TradeBookWidget {...makeDockviewPanelProps()} />);

    // The misleading empty state must not appear while the query is errored
    expect(screen.queryByText("No trades today")).not.toBeInTheDocument();
    expect(screen.getByText(/Failed to load trades: OpenAlgo server error/)).toBeInTheDocument();
    expect(screen.getByText("Trade book unavailable — retry above")).toBeInTheDocument();

    // Retry triggers a refetch
    fireEvent.click(screen.getByText("Retry"));
    expect(mockRefetch).toHaveBeenCalled();
  });

  it("does not fetch or refresh tradebook without a broker connection", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockUseTradebook.mockReturnValue(queryResult({ data: [] }));
    render(<TradeBookWidget {...makeDockviewPanelProps()} />);

    expect(mockUseTradebook).toHaveBeenCalledWith({ enabled: false });
    expect(screen.getByText("Broker required")).toBeInTheDocument();
    expect(screen.getByText("Connect a broker to load trades")).toBeInTheDocument();
    expect(screen.queryByLabelText("Refresh tradebook")).not.toBeInTheDocument();
  });
});
