/**
 * HoldingsWidget.test.tsx
 *
 * Tests for the Holdings widget — renders holding rows from useHoldings().
 * Verifies empty state, data rendering, and search filtering.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";

// Mock useHoldings hook
const mockRefetch = vi.fn();
const mockUseHoldings = vi.fn();
const mockUseBrokerConnected = vi.fn();
const mockUseAccountReadsEnabled = vi.fn();

vi.mock("@/hooks/useHoldings", () => ({
  useHoldings: (...args: unknown[]) => mockUseHoldings(...args),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => mockUseBrokerConnected(),
}));

vi.mock("@/hooks/useAccountReadsEnabled", () => ({
  useAccountReadsEnabled: () => mockUseAccountReadsEnabled(),
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
    vi.clearAllMocks();
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseAccountReadsEnabled.mockReturnValue(true);
  });

  it("renders without crashing", () => {
    mockUseHoldings.mockReturnValue(queryResult({ data: [] }));
    const { container } = render(<HoldingsWidget {...makeWidgetPanelProps()} />);
    expect(container).toBeTruthy();
  });

  it("shows 'No holdings' when data is empty", () => {
    mockUseHoldings.mockReturnValue(queryResult({ data: [] }));
    render(<HoldingsWidget {...makeWidgetPanelProps()} />);
    expect(screen.getByText("No holdings")).toBeInTheDocument();
  });

  it("displays holding rows with symbol, qty, and P&L", () => {
    mockUseHoldings.mockReturnValue(queryResult({ data: SAMPLE_HOLDINGS }));
    render(<HoldingsWidget {...makeWidgetPanelProps()} />);

    // Symbols should be displayed
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText("TCS")).toBeInTheDocument();

    // Quantities should be displayed
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("shows the holdings count in the header", () => {
    mockUseHoldings.mockReturnValue(queryResult({ data: SAMPLE_HOLDINGS }));
    render(<HoldingsWidget {...makeWidgetPanelProps()} />);

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
    render(<HoldingsWidget {...makeWidgetPanelProps()} />);

    expect(screen.getByText(/failed to load holdings/i)).toBeInTheDocument();
  });

  it("filters holdings by symbol search", () => {
    mockUseHoldings.mockReturnValue(queryResult({ data: SAMPLE_HOLDINGS }));
    render(<HoldingsWidget {...makeWidgetPanelProps()} />);

    const searchInput = screen.getByPlaceholderText(/filter symbol/i);
    fireEvent.change(searchInput, { target: { value: "REL" } });

    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    // TCS should be filtered out — it should not appear in the table
    expect(screen.queryByText("TCS")).not.toBeInTheDocument();
  });

  it("sorts quantities numerically and retains sorting when a search is cleared", () => {
    mockUseHoldings.mockReturnValue(queryResult({ data: SAMPLE_HOLDINGS }));
    render(<HoldingsWidget {...makeWidgetPanelProps()} />);

    const symbols = () => Array.from(screen.getByRole("table").querySelectorAll("tbody tr"))
      .map((row) => row.querySelector("td")?.textContent);
    const quantityHeader = screen.getByRole("columnheader", { name: /qty/i });

    fireEvent.click(quantityHeader);
    expect(symbols()).toEqual(["RELIANCE", "TCS"]);
    fireEvent.click(quantityHeader);
    expect(symbols()).toEqual(["TCS", "RELIANCE"]);

    const search = screen.getByPlaceholderText(/filter symbol/i);
    fireEvent.change(search, { target: { value: "rel" } });
    expect(symbols()).toEqual(["RELIANCE"]);
    fireEvent.change(search, { target: { value: "" } });
    expect(symbols()).toEqual(["TCS", "RELIANCE"]);
  });

  it("does not fetch or refresh holdings without a broker connection", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockUseAccountReadsEnabled.mockReturnValue(false);
    mockUseHoldings.mockReturnValue(queryResult({ data: [] }));
    render(<HoldingsWidget {...makeWidgetPanelProps()} />);

    expect(mockUseHoldings).toHaveBeenCalledWith({ enabled: false });
    expect(screen.getByText("Broker required")).toBeInTheDocument();
    expect(screen.getByText("Connect a broker to load holdings")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /export portfolio report/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Refresh holdings")).not.toBeInTheDocument();
  });
});
