import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";

// ---------------------------------------------------------------------------
// Mocks — factory functions only; no variable references (hoisting safety)
// ---------------------------------------------------------------------------

const mockPlaceOrder = vi.hoisted(() => vi.fn());
const mockGetSymbol = vi.hoisted(() => vi.fn());

vi.mock("@/services/api", () => ({
  placeOrder: mockPlaceOrder,
  getSymbol: mockGetSymbol,
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) =>
    selector({ mode: "practice" }),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import QuickTradeWidget from "../QuickTradeWidget";

function renderQuickTrade(params: Record<string, unknown> = {}) {
  return render(<QuickTradeWidget {...makeDockviewPanelProps({ params })} />);
}

beforeEach(() => {
  mockPlaceOrder.mockReset();
  mockPlaceOrder.mockResolvedValue({ orderId: "QT001" });
  mockGetSymbol.mockReset();
  mockGetSymbol.mockResolvedValue({
    symbol: "NIFTY",
    exchange: "NSE",
    lotsize: 1,
    tick_size: 0.05,
  });
});

describe("QuickTradeWidget", () => {
  it("renders widget header with symbol and exchange from panel params", () => {
    renderQuickTrade({ symbol: "RELIANCE", exchange: "NSE" });
    expect(screen.getByText("Quick Trade")).toBeTruthy();
    expect(screen.getByText("RELIANCE")).toBeTruthy();
    expect(screen.getByText("NSE")).toBeTruthy();
  });

  it("renders lot preset buttons", () => {
    renderQuickTrade();
    // LOT_PRESETS: 1, 2, 5, 10
    const group = screen.getByRole("group", { name: "Lot size presets" });
    expect(group).toBeTruthy();
    expect(group.querySelectorAll("button").length).toBe(4);
  });

  it("renders BUY and SELL buttons", () => {
    renderQuickTrade({ symbol: "NIFTY", exchange: "NSE" });
    expect(screen.getByRole("button", { name: /buy 1 lots/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /sell 1 lots/i })).toBeTruthy();
  });

  it("shows limit price input when LIMIT order type is selected", () => {
    renderQuickTrade();
    const limitBtn = screen.getByRole("button", { name: /LIMIT/i });
    fireEvent.click(limitBtn);
    expect(screen.getByLabelText("Limit price")).toBeTruthy();
  });

  it("does not show limit price input when MARKET is selected", () => {
    renderQuickTrade();
    expect(screen.queryByLabelText("Limit price")).toBeNull();
  });

  it("sends quantity = lots × lot size for a derivatives contract", async () => {
    mockGetSymbol.mockResolvedValue({
      symbol: "BANKNIFTY26JUN56000CE",
      exchange: "NFO",
      lotsize: 30,
      tick_size: 0.05,
    });
    renderQuickTrade({ symbol: "BANKNIFTY26JUN56000CE", exchange: "NFO" });

    // Wait for the lot size to be confirmed (the qty summary appears)
    await screen.findByText(/Qty: 1 × 30 = 30/);

    // Select 2 lots, then BUY
    fireEvent.click(screen.getByRole("button", { name: "2" }));
    fireEvent.click(screen.getByRole("button", { name: /buy 2 lots/i }));

    await waitFor(() => {
      expect(mockPlaceOrder).toHaveBeenCalledWith(
        expect.objectContaining({
          symbol: "BANKNIFTY26JUN56000CE",
          exchange: "NFO",
          action: "BUY",
          quantity: 60, // 2 lots × 30 — NOT the raw preset number
          product: "MIS",
          orderType: "MARKET",
        }),
      );
    });
  });

  it("blocks derivative orders (fail closed) while the lot size is unverified", async () => {
    mockGetSymbol.mockRejectedValue(new Error("symbol not found"));
    renderQuickTrade({ symbol: "BANKNIFTY26JUN56000CE", exchange: "NFO" });

    await screen.findByText(/Lot size unverified — orders blocked/);

    fireEvent.click(screen.getByRole("button", { name: /buy 1 lots/i }));

    await waitFor(() => {
      expect(screen.getByText(/is unverified — order not sent/)).toBeInTheDocument();
    });
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("uses quantity = lots for an equity (lot size 1)", async () => {
    renderQuickTrade({ symbol: "RELIANCE", exchange: "NSE" });
    await screen.findByText(/Qty: 1 × 1 = 1/);

    fireEvent.click(screen.getByRole("button", { name: "5" }));
    fireEvent.click(screen.getByRole("button", { name: /sell 5 lots/i }));

    await waitFor(() => {
      expect(mockPlaceOrder).toHaveBeenCalledWith(
        expect.objectContaining({ symbol: "RELIANCE", action: "SELL", quantity: 5 }),
      );
    });
  });

  it("requires confirmation for a 10-lot order (threshold is reachable)", async () => {
    renderQuickTrade({ symbol: "RELIANCE", exchange: "NSE" });
    await screen.findByText(/Qty: 1 × 1 = 1/);

    fireEvent.click(screen.getByRole("button", { name: "10" }));
    fireEvent.click(screen.getByRole("button", { name: /buy 10 lots/i }));

    // Confirm dialog appears; nothing sent yet
    expect(screen.getByRole("dialog", { name: /confirm large order/i })).toBeInTheDocument();
    expect(mockPlaceOrder).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /confirm buy/i }));
    await waitFor(() => {
      expect(mockPlaceOrder).toHaveBeenCalledWith(
        expect.objectContaining({ action: "BUY", quantity: 10 }),
      );
    });
  });

  it("shows success status after successful order", async () => {
    renderQuickTrade({ symbol: "NIFTY", exchange: "NSE" });
    await screen.findByText(/Qty: 1 × 1 = 1/);
    fireEvent.click(screen.getByRole("button", { name: /buy 1 lots/i }));
    await waitFor(() => {
      expect(screen.getByRole("status")).toBeTruthy();
      expect(screen.getByText(/BUY order placed/i)).toBeTruthy();
    });
  });

  it("shows error status when placeOrder throws", async () => {
    mockPlaceOrder.mockRejectedValueOnce(new Error("Connection refused"));
    renderQuickTrade({ symbol: "NIFTY", exchange: "NSE" });
    await screen.findByText(/Qty: 1 × 1 = 1/);
    fireEvent.click(screen.getByRole("button", { name: /sell 1 lots/i }));
    await waitFor(() => {
      expect(screen.getByRole("status")).toBeTruthy();
      expect(screen.getByText(/Connection refused/i)).toBeTruthy();
    });
  });
});
