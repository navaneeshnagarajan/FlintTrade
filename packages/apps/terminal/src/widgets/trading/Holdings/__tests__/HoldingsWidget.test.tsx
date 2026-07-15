/**
 * HoldingsWidget.test.tsx
 *
 * Tests for the Holdings widget — renders holding rows from useHoldings().
 * Verifies empty state, data rendering, and search filtering.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";

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

// Positions are fetched for the portfolio-report export.
const mockUsePositions = vi.fn();
vi.mock("@/hooks/usePositions", () => ({
  usePositions: (...args: unknown[]) => mockUsePositions(...args),
}));

const mockDownloadReport = vi.fn();
vi.mock("@/services/ftApi.data", () => ({
  downloadPortfolioReport: (...args: unknown[]) => mockDownloadReport(...args),
}));

const mockEmit = vi.fn();
vi.mock("@/components/NotificationCentre/useNotificationFeed", () => ({
  emitNotification: (...args: unknown[]) => mockEmit(...args),
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
    // clearAllMocks (not restoreAllMocks) so vi.fn() CALL HISTORY is reset
    // between tests — the "nothing to export" assertion checks not-called.
    vi.clearAllMocks();
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseAccountReadsEnabled.mockReturnValue(true);
    mockUsePositions.mockReturnValue({ data: [] });
  });

  it("renders without crashing", () => {
    mockUseHoldings.mockReturnValue(queryResult({ data: [] }));
    const { container } = render(<HoldingsWidget {...makeDockviewPanelProps()} />);
    expect(container).toBeTruthy();
  });

  it("shows 'No holdings' when data is empty", () => {
    mockUseHoldings.mockReturnValue(queryResult({ data: [] }));
    render(<HoldingsWidget {...makeDockviewPanelProps()} />);
    expect(screen.getByText("No holdings")).toBeInTheDocument();
  });

  it("displays holding rows with symbol, qty, and P&L", () => {
    mockUseHoldings.mockReturnValue(queryResult({ data: SAMPLE_HOLDINGS }));
    render(<HoldingsWidget {...makeDockviewPanelProps()} />);

    // Symbols should be displayed
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText("TCS")).toBeInTheDocument();

    // Quantities should be displayed
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("shows the holdings count in the header", () => {
    mockUseHoldings.mockReturnValue(queryResult({ data: SAMPLE_HOLDINGS }));
    render(<HoldingsWidget {...makeDockviewPanelProps()} />);

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
    render(<HoldingsWidget {...makeDockviewPanelProps()} />);

    expect(screen.getByText(/failed to load holdings/i)).toBeInTheDocument();
  });

  it("filters holdings by symbol search", () => {
    mockUseHoldings.mockReturnValue(queryResult({ data: SAMPLE_HOLDINGS }));
    render(<HoldingsWidget {...makeDockviewPanelProps()} />);

    const searchInput = screen.getByPlaceholderText(/filter symbol/i);
    fireEvent.change(searchInput, { target: { value: "REL" } });

    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    // TCS should be filtered out — it should not appear in the table
    expect(screen.queryByText("TCS")).not.toBeInTheDocument();
  });

  // ── Portfolio report export ────────────────────────────────────────────

  it("exports a portfolio report (positions + holdings) and notifies on success", async () => {
    mockUseHoldings.mockReturnValue(queryResult({ data: SAMPLE_HOLDINGS }));
    mockUsePositions.mockReturnValue({
      data: [{ symbol: "NIFTY", quantity: 50, ltp: 100, pnl: 500 }],
    });
    mockDownloadReport.mockResolvedValue(3);
    render(<HoldingsWidget {...makeDockviewPanelProps()} />);

    fireEvent.click(screen.getByRole("button", { name: /export portfolio report to excel/i }));

    await vi.waitFor(() => expect(mockDownloadReport).toHaveBeenCalledTimes(1));
    // positions (arg 0) and holdings (arg 1) both passed.
    expect(mockDownloadReport.mock.calls[0][0]).toHaveLength(1);
    expect(mockDownloadReport.mock.calls[0][1]).toHaveLength(2);
    await vi.waitFor(() =>
      expect(mockEmit).toHaveBeenCalledWith(
        expect.objectContaining({ category: "system", title: "Portfolio report exported" }),
      ),
    );
  });

  it("emits an alert when there is nothing to export", () => {
    mockUseHoldings.mockReturnValue(queryResult({ data: [] }));
    mockUsePositions.mockReturnValue({ data: [] });
    render(<HoldingsWidget {...makeDockviewPanelProps()} />);

    fireEvent.click(screen.getByRole("button", { name: /export portfolio report to excel/i }));
    expect(mockEmit).toHaveBeenCalledWith(
      expect.objectContaining({ category: "alert", title: "Nothing to export" }),
    );
    expect(mockDownloadReport).not.toHaveBeenCalled();
  });

  it("does not fetch, refresh, or export holdings without a broker connection", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockUseAccountReadsEnabled.mockReturnValue(false);
    mockUseHoldings.mockReturnValue(queryResult({ data: [] }));
    mockUsePositions.mockReturnValue({ data: [] });
    render(<HoldingsWidget {...makeDockviewPanelProps()} />);

    expect(mockUseHoldings).toHaveBeenCalledWith({ enabled: false });
    expect(mockUsePositions).toHaveBeenCalledWith({ enabled: false });
    expect(screen.getByText("Broker required")).toBeInTheDocument();
    expect(screen.getByText("Connect a broker to load holdings")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /export portfolio report/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Refresh holdings")).not.toBeInTheDocument();
  });
});
