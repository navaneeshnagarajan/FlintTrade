import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks — factory functions only; no variable references (hoisting safety)
// ---------------------------------------------------------------------------

vi.mock("@/services/api", () => ({
  placeOrder: vi.fn().mockResolvedValue({ orderId: "QT001" }),
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

import { placeOrder } from "@/services/api";
import QuickTradeWidget from "../QuickTradeWidget";

const mockPlaceOrder = placeOrder as ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockPlaceOrder.mockReset();
  mockPlaceOrder.mockResolvedValue({ orderId: "QT001" });
});

describe("QuickTradeWidget", () => {
  it("renders widget header with symbol and exchange", () => {
    render(<QuickTradeWidget symbol="NIFTY" exchange="NSE" />);
    expect(screen.getByText("Quick Trade")).toBeTruthy();
    expect(screen.getByText("NIFTY")).toBeTruthy();
    expect(screen.getByText("NSE")).toBeTruthy();
  });

  it("renders lot preset buttons", () => {
    render(<QuickTradeWidget />);
    // LOT_PRESETS: 1, 2, 5, 10
    const group = screen.getByRole("group", { name: "Lot size presets" });
    expect(group).toBeTruthy();
    expect(group.querySelectorAll("button").length).toBe(4);
  });

  it("renders BUY and SELL buttons", () => {
    render(<QuickTradeWidget symbol="NIFTY" exchange="NSE" />);
    expect(screen.getByRole("button", { name: /buy 1 lots/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /sell 1 lots/i })).toBeTruthy();
  });

  it("shows limit price input when LIMIT order type is selected", () => {
    render(<QuickTradeWidget />);
    const limitBtn = screen.getByRole("button", { name: /LIMIT/i });
    fireEvent.click(limitBtn);
    expect(screen.getByLabelText("Limit price")).toBeTruthy();
  });

  it("does not show limit price input when MARKET is selected", () => {
    render(<QuickTradeWidget />);
    expect(screen.queryByLabelText("Limit price")).toBeNull();
  });

  it("calls placeOrder with correct params on BUY click", async () => {
    render(<QuickTradeWidget symbol="BANKNIFTY" exchange="NFO" />);
    const buyBtn = screen.getByRole("button", { name: /buy/i });
    fireEvent.click(buyBtn);
    await waitFor(() => {
      expect(mockPlaceOrder).toHaveBeenCalledWith(
        expect.objectContaining({
          symbol: "BANKNIFTY",
          exchange: "NFO",
          action: "BUY",
          quantity: 1,
          product: "MIS",
          orderType: "MARKET",
        }),
      );
    });
  });

  it("shows success status after successful order", async () => {
    render(<QuickTradeWidget symbol="NIFTY" exchange="NSE" />);
    fireEvent.click(screen.getByRole("button", { name: /buy/i }));
    await waitFor(() => {
      expect(screen.getByRole("status")).toBeTruthy();
      expect(screen.getByText(/BUY order placed/i)).toBeTruthy();
    });
  });

  it("shows error status when placeOrder throws", async () => {
    mockPlaceOrder.mockRejectedValueOnce(new Error("Connection refused"));
    render(<QuickTradeWidget symbol="NIFTY" exchange="NSE" />);
    fireEvent.click(screen.getByRole("button", { name: /sell/i }));
    await waitFor(() => {
      expect(screen.getByRole("status")).toBeTruthy();
      expect(screen.getByText(/Connection refused/i)).toBeTruthy();
    });
  });
});
