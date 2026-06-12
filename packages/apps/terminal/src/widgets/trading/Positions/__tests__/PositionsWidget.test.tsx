/**
 * PositionsWidget.test.tsx
 *
 * Tests for the Positions trading widget.
 * Verifies rendering, empty state, position row display, and the two
 * gated safety actions (per-row Convert and the typed exit-all flow).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";

// Force DEV mode so ftApi.helpers' getBase() returns "/ft-api" — the convert
// and exit-all actions go through the real helpers with a stubbed fetch.
vi.stubEnv("DEV", true);

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

// ftApi.helpers reads these stores for auth headers on every call.
vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: { getState: () => ({ apiKey: "" }) },
}));
vi.mock("@/stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: "" }) },
}));

const mockDownloadExcel = vi.fn();
vi.mock("@/services/ftApi.data", () => ({
  downloadExcel: (...args: unknown[]) => mockDownloadExcel(...args),
}));

const mockEmitNotification = vi.fn();
vi.mock("@/components/NotificationCentre/useNotificationFeed", () => ({
  emitNotification: (...args: unknown[]) => mockEmitNotification(...args),
}));

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------

import PositionsWidget from "../PositionsWidget";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = makeDockviewPanelProps();

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

  // ── Excel export ─────────────────────────────────────────────────────────

  it("does not show the export button when there are no positions", () => {
    mockUsePositions.mockReturnValue(queryResult({ data: [] }));
    render(<PositionsWidget {...defaultProps} />);
    expect(screen.queryByRole("button", { name: /export positions to excel/i })).toBeNull();
  });

  it("exports the positions and emits a success notification", async () => {
    mockDownloadExcel.mockResolvedValue(2);
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          { symbol: "NIFTY", pnl: 500, quantity: 50, ltp: 100, average_price: 90 },
          { symbol: "BANKNIFTY", pnl: -200, quantity: 25, ltp: 200, average_price: 190 },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    fireEvent.click(screen.getByRole("button", { name: /export positions to excel/i }));

    await vi.waitFor(() => expect(mockDownloadExcel).toHaveBeenCalledTimes(1));
    // Exports the mapped rows under the "Positions" sheet.
    expect(mockDownloadExcel.mock.calls[0][1]).toBe("Positions");
    expect(mockDownloadExcel.mock.calls[0][0]).toHaveLength(2);
    await vi.waitFor(() =>
      expect(mockEmitNotification).toHaveBeenCalledWith(
        expect.objectContaining({ category: "system", title: "Positions exported" }),
      ),
    );
  });

  it("emits an alert notification when the export fails", async () => {
    mockDownloadExcel.mockRejectedValue(new Error("backend down"));
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [{ symbol: "NIFTY", pnl: 500, quantity: 50, ltp: 100, average_price: 90 }],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    fireEvent.click(screen.getByRole("button", { name: /export positions to excel/i }));

    await vi.waitFor(() =>
      expect(mockEmitNotification).toHaveBeenCalledWith(
        expect.objectContaining({ category: "alert", title: "Export failed", body: "backend down" }),
      ),
    );
  });

  // ── Convert + exit-all safety actions ───────────────────────────────────

  describe("position actions", () => {
    afterEach(() => {
      vi.unstubAllGlobals();
    });

    function stubFetch(body: unknown = { status: "success", data: { ok: true } }, status = 200) {
      const fetchMock = vi.fn().mockResolvedValue(
        new Response(JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        }),
      );
      vi.stubGlobal("fetch", fetchMock);
      return fetchMock;
    }

    const positions = [
      {
        symbol: "NIFTY24APR24000CE",
        pnl: 1200,
        quantity: 75,
        ltp: 150,
        average_price: 134,
        exchange: "NFO",
        product: "NRML",
      },
      {
        symbol: "RELIANCE",
        pnl: -200,
        quantity: -10,
        ltp: 2900,
        average_price: 2880,
        exchange: "NSE",
        product: "MIS",
      },
    ];

    it("converts a position through the gated convert route", async () => {
      const fetchMock = stubFetch();
      const mockRefetch = vi.fn();
      mockUsePositions.mockReturnValue(queryResult({ data: positions, refetch: mockRefetch }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Convert NIFTY24APR24000CE" }));
      expect(screen.getByText("Convert position")).toBeInTheDocument();

      // NRML defaults to MIS as the target product — confirm without
      // touching the select.
      fireEvent.click(
        screen.getByRole("button", { name: "Convert NIFTY24APR24000CE to MIS" }),
      );

      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/ft-api/api/v1/positions/convert");
      expect(init.method).toBe("POST");
      const body = JSON.parse(String(init.body)) as {
        broker: string;
        req: Record<string, unknown>;
      };
      expect(body.broker).toBe("openalgo");
      expect(body.req).toMatchObject({
        symbol: "NIFTY24APR24000CE",
        exchange: "NFO",
        quantity: 75,
        position_type: "LONG",
        from_product: "NRML",
        to_product: "MIS",
        new_product: "MIS",
      });

      await waitFor(() => expect(mockRefetch).toHaveBeenCalledTimes(1));
      expect(mockEmitNotification).toHaveBeenCalledWith(
        expect.objectContaining({ category: "system", title: "Position conversion submitted" }),
      );
    });

    it("surfaces the mode-guard 403 honestly inside the convert dialog", async () => {
      stubFetch(
        { status: "error", message: "Live orders are allowed in live mode only — switch mode first" },
        403,
      );
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Convert NIFTY24APR24000CE" }));
      fireEvent.click(
        screen.getByRole("button", { name: "Convert NIFTY24APR24000CE to MIS" }),
      );

      expect(
        await screen.findByText("Live orders are allowed in live mode only — switch mode first"),
      ).toBeInTheDocument();
      // The dialog stays open so the operator can read what blocked it.
      expect(screen.getByText("Convert position")).toBeInTheDocument();
    });

    it("blocks exit-all until the operator types EXIT, then posts the confirmed body", async () => {
      const fetchMock = stubFetch({ status: "success", data: { status: "ok" } });
      const mockRefetch = vi.fn();
      mockUsePositions.mockReturnValue(queryResult({ data: positions, refetch: mockRefetch }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Exit all positions" }));
      expect(screen.getByText("Exit all positions?")).toBeInTheDocument();

      const confirmButton = screen.getByRole("button", { name: "Confirm exit all positions" });
      expect(confirmButton).toBeDisabled();

      // Clicking while disabled must never reach the backend.
      fireEvent.click(confirmButton);
      expect(fetchMock).not.toHaveBeenCalled();

      // A wrong phrase keeps it blocked.
      const input = screen.getByLabelText(/type EXIT \(in capitals\) to confirm/i);
      fireEvent.change(input, { target: { value: "exit" } });
      expect(confirmButton).toBeDisabled();
      fireEvent.click(confirmButton);
      expect(fetchMock).not.toHaveBeenCalled();

      // The exact phrase unlocks the action.
      fireEvent.change(input, { target: { value: "EXIT" } });
      expect(confirmButton).toBeEnabled();
      fireEvent.click(confirmButton);

      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/ft-api/api/v1/positions/exit-all");
      expect(init.method).toBe("POST");
      expect(JSON.parse(String(init.body))).toStrictEqual({ confirm: true, broker: "openalgo" });

      await waitFor(() => expect(mockRefetch).toHaveBeenCalledTimes(1));
      expect(mockEmitNotification).toHaveBeenCalledWith(
        expect.objectContaining({ category: "system", title: "Exit-all submitted" }),
      );
    });

    it("surfaces the mode-guard 403 honestly inside the exit-all dialog", async () => {
      stubFetch(
        { status: "error", message: "Live mode is locked — verify your PIN to unlock live trading" },
        403,
      );
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Exit all positions" }));
      fireEvent.change(screen.getByLabelText(/type EXIT \(in capitals\) to confirm/i), {
        target: { value: "EXIT" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Confirm exit all positions" }));

      expect(
        await screen.findByText("Live mode is locked — verify your PIN to unlock live trading"),
      ).toBeInTheDocument();
      expect(screen.getByText("Exit all positions?")).toBeInTheDocument();
    });
  });
});
