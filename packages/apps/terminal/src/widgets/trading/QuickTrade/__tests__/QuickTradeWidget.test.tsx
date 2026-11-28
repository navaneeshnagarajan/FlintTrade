import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";

// ---------------------------------------------------------------------------
// Mocks — factory functions only; no variable references (hoisting safety)
// ---------------------------------------------------------------------------

const { mockPlaceOrder, mockGetSymbol, OrderApiError } = vi.hoisted(() => {
  class OrderApiError extends Error {
    readonly status: number;
    readonly body: unknown;
    constructor(message: string, status: number, body: unknown) {
      super(message);
      this.name = "OrderApiError";
      this.status = status;
      this.body = body;
    }
  }
  return {
    mockPlaceOrder: vi.fn(),
    mockGetSymbol: vi.fn(),
    OrderApiError,
  };
});

vi.mock("@/services/api", () => ({
  placeOrder: mockPlaceOrder,
  getSymbol: mockGetSymbol,
  OrderApiError,
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

import { createStore, Provider } from "jotai";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";
import { selectedSymbolAtom } from "@/atoms/marketAtoms";
import { broadcastInstrument, DEFAULT_CHANNEL_ID } from "@/services/fdc3/channels";
import QuickTradeWidget from "../QuickTradeWidget";

function renderQuickTrade(params: Record<string, unknown> = {}) {
  return render(<QuickTradeWidget {...makeWidgetPanelProps({ params })} />);
}

beforeEach(() => {
  useOperatorSignalStore.setState({ decisionStatus: "down" });
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

  it("fails closed with a select-an-instrument state when there are no params and no selection", () => {
    // Item 7: no panel params + no workspace selection must NOT default to
    // NIFTY/NSE — a one-click widget silently targeting an instrument the
    // trader never chose is an order-safety bug.
    renderQuickTrade();

    expect(screen.getByText("Select an instrument")).toBeInTheDocument();
    expect(screen.queryByText("NIFTY")).toBeNull();
    expect(screen.queryByRole("button", { name: /buy/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /sell/i })).toBeNull();
    expect(mockGetSymbol).not.toHaveBeenCalled();
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("follows the workspace's selected instrument when no panel params are given", async () => {
    const store = createStore();
    store.set(selectedSymbolAtom, { symbol: "TCS", exchange: "NSE" });

    render(
      <Provider store={store}>
        <QuickTradeWidget {...makeWidgetPanelProps({ params: {} })} />
      </Provider>,
    );

    expect(screen.getByText("TCS")).toBeInTheDocument();
    expect(screen.queryByText("Select an instrument")).toBeNull();
    await screen.findByText(/Qty: 1 × 1 = 1/);
  });

  it("follows an instrument broadcast on its FDC3 channel", async () => {
    const store = createStore();
    render(
      <Provider store={store}>
        <QuickTradeWidget
          {...makeWidgetPanelProps({ params: { channel: "fdc3.channel.green" } })}
        />
      </Provider>,
    );

    // Nothing broadcast yet — the fail-closed empty state stands.
    expect(screen.getByText("Select an instrument")).toBeInTheDocument();

    act(() => broadcastInstrument(store, "fdc3.channel.green", { symbol: "INFY", exchange: "NSE" }));

    expect(screen.getByText("INFY")).toBeInTheDocument();
    expect(screen.queryByText("Select an instrument")).toBeNull();
    await screen.findByText(/Qty: 1 × 1 = 1/);
  });

  it("joined to no channel (channel: none) ignores broadcasts and stays fail-closed", () => {
    const store = createStore();
    render(
      <Provider store={store}>
        <QuickTradeWidget {...makeWidgetPanelProps({ params: { channel: "none" } })} />
      </Provider>,
    );

    act(() => broadcastInstrument(store, DEFAULT_CHANNEL_ID, { symbol: "TCS", exchange: "NSE" }));

    expect(screen.getByText("Select an instrument")).toBeInTheDocument();
    expect(screen.queryByText("TCS")).toBeNull();
    expect(screen.queryByRole("button", { name: /buy/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /sell/i })).toBeNull();
    expect(mockGetSymbol).not.toHaveBeenCalled();
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("keeps a panel-pinned symbol over a broadcast on its channel", () => {
    const store = createStore();
    render(
      <Provider store={store}>
        <QuickTradeWidget
          {...makeWidgetPanelProps({ params: { symbol: "RELIANCE", exchange: "NSE" } })}
        />
      </Provider>,
    );

    act(() => broadcastInstrument(store, DEFAULT_CHANNEL_ID, { symbol: "TCS", exchange: "BSE" }));

    // The pin wins — the ticket must not silently retarget under the trader.
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(screen.queryByText("TCS")).toBeNull();
  });

  it("renders lot preset buttons", () => {
    renderQuickTrade({ symbol: "NIFTY", exchange: "NSE" });
    // LOT_PRESETS: 1, 2, 5, 10
    const group = screen.getByRole("group", { name: "Lot size presets" });
    expect(group).toBeTruthy();
    expect(group.querySelectorAll("button").length).toBe(4);
  });

  it("renders BUY and SELL buttons", () => {
    renderQuickTrade({ symbol: "NIFTY", exchange: "NSE" });
    expect(screen.getByRole("button", { name: /buy 1 lot /i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /sell 1 lot /i })).toBeTruthy();
  });

  it("shows limit price input when LIMIT order type is selected", () => {
    renderQuickTrade({ symbol: "NIFTY", exchange: "NSE" });
    const limitBtn = screen.getByRole("button", { name: /LIMIT/i });
    fireEvent.click(limitBtn);
    expect(screen.getByLabelText("Limit price")).toBeTruthy();
  });

  it("does not show limit price input when MARKET is selected", () => {
    renderQuickTrade({ symbol: "NIFTY", exchange: "NSE" });
    expect(screen.queryByLabelText("Limit price")).toBeNull();
  });


  it("defaults an option ticket to LIMIT and shows the market refusal before submit", async () => {
    mockGetSymbol.mockResolvedValue({
      symbol: "BANKNIFTY26JUN56000CE",
      exchange: "NFO",
      lotsize: 30,
      tick_size: 0.05,
    });
    renderQuickTrade({ symbol: "BANKNIFTY26JUN56000CE", exchange: "NFO" });
    await screen.findByText(/Qty: 1 × 30 = 30/);
    expect(screen.getByLabelText("Limit price")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /MARKET/i }));
    expect(await screen.findByTestId("order-rule-line")).toHaveTextContent(
      "Market orders aren't accepted on options. Use a limit price.",
    );
    expect(screen.getByRole("button", { name: /buy 1 lot /i })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /buy 1 lot /i }));
    expect(mockPlaceOrder).not.toHaveBeenCalled();
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
    expect(screen.getByLabelText("Limit price")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Limit price"), { target: { value: "120.5" } });
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
          orderType: "LIMIT",
          price: 120.5,
        }),
      );
    });
  });

  it("disables Buy and Sell and names the underlying when the lot lookup fails", async () => {
    mockGetSymbol.mockRejectedValue(new Error("symbol not found"));
    renderQuickTrade({ symbol: "BANKNIFTY26JUN56000CE", exchange: "NFO" });

    expect(await screen.findByText("The lot size for BANKNIFTY isn't verified.")).toBeInTheDocument();
    const buy = screen.getByRole("button", { name: /buy 1 lot /i });
    const sell = screen.getByRole("button", { name: /sell 1 lot /i });
    expect(buy).toBeDisabled();
    expect(sell).toBeDisabled();
    fireEvent.click(buy);
    fireEvent.click(sell);
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("never sends a derivative at lot 1 when the broker reports no lot", async () => {
    mockGetSymbol.mockResolvedValue({
      symbol: "NIFTY26DECFUT",
      exchange: "NFO",
      lotsize: 0,
      tick_size: 0.05,
    });
    renderQuickTrade({ symbol: "NIFTY26DECFUT", exchange: "NFO" });

    expect(await screen.findByText("The lot size for NIFTY isn't verified.")).toBeInTheDocument();
    expect(screen.queryByText(/Qty: 1 × 1/)).toBeNull();
    const buy = screen.getByRole("button", { name: /buy 1 lot /i });
    expect(buy).toBeDisabled();
    fireEvent.click(buy);
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

  it("sends the admission note with the place", async () => {
    renderQuickTrade({ symbol: "RELIANCE", exchange: "NSE" });
    await screen.findByText(/Qty: 1 × 1 = 1/);
    fireEvent.change(screen.getByLabelText("Add a reason (optional)"), {
      target: { value: "Planned breakout" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sell 1 lot of/i }));
    await waitFor(() => {
      expect(mockPlaceOrder).toHaveBeenCalledWith(
        expect.objectContaining({ action: "SELL", quantity: 1, rationale: "Planned breakout" }),
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
    fireEvent.click(screen.getByRole("button", { name: /buy 1 lot /i }));
    await waitFor(() => {
      expect(screen.getByRole("status")).toBeTruthy();
      expect(screen.getByText(/BUY order placed/i)).toBeTruthy();
    });
  });

  it("shows error status when placeOrder throws", async () => {
    mockPlaceOrder.mockRejectedValueOnce(new Error("Connection refused"));
    renderQuickTrade({ symbol: "NIFTY", exchange: "NSE" });
    await screen.findByText(/Qty: 1 × 1 = 1/);
    fireEvent.click(screen.getByRole("button", { name: /sell 1 lot /i }));
    await waitFor(() => {
      expect(screen.getByRole("status")).toBeTruthy();
      expect(screen.getByText(/Connection refused/i)).toBeTruthy();
    });
  });

  it("shows Laya denied under Buy and Sell and leaves both off", async () => {
    mockPlaceOrder.mockRejectedValueOnce(new OrderApiError("Quantity must be a positive whole number.", 403, {
      code: "decision_model_denied",
      reason: "Quantity must be a positive whole number.",
      message: "Quantity must be a positive whole number.",
      limits: { max_quantity: 1 },
    }));
    renderQuickTrade({ symbol: "NIFTY", exchange: "NSE" });
    await screen.findByText(/Qty: 1 × 1 = 1/);
    fireEvent.click(screen.getByRole("button", { name: /buy 1 lot /i }));
    const denied = await screen.findByTestId("laya-denied");
    expect(denied).toHaveTextContent("Denied by decision model");
    expect(denied).toHaveTextContent("Quantity must be a positive whole number.");
    expect(denied).toHaveTextContent("Max quantity 1.");
    expect(screen.getByRole("button", { name: /buy 1 lot /i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /sell 1 lot /i })).toBeDisabled();
    expect(screen.queryByText(/Approved by Laya/)).not.toBeInTheDocument();
  });

  it("clears a Laya denial when decision status recovers and leaves Buy and Sell retryable", async () => {
    mockPlaceOrder.mockRejectedValueOnce(new OrderApiError(
      "Not placed. Decision model is down. Start it from Status.",
      403,
      {
      code: "decision_model_denied",
      reason: "Not placed. Decision model is down. Start it from Status.",
      message: "Not placed. Decision model is down. Start it from Status.",      limits: { max_quantity: 100 },
    }));
    renderQuickTrade({ symbol: "NIFTY", exchange: "NSE" });
    await screen.findByText(/Qty: 1 × 1 = 1/);
    fireEvent.click(screen.getByRole("button", { name: /buy 1 lot /i }));
    const denied = await screen.findByTestId("laya-denied");
    expect(denied).toHaveTextContent("Not placed. Decision model is down. Start it from Status.");
    expect(denied).not.toHaveTextContent("Max quantity");
    expect(screen.getByRole("button", { name: /buy 1 lot /i })).toBeDisabled();

    act(() => {
      useOperatorSignalStore.setState({ decisionStatus: "ready" });
    });

    expect(screen.queryByTestId("laya-denied")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /buy 1 lot /i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /sell 1 lot /i })).toBeEnabled();
  });

  it("refuses a LIMIT order with no price instead of sending it at zero", async () => {
    // A ₹0 limit price is a guaranteed broker rejection, and a lenient bridge
    // could treat it as marketable — turning a price-protected order into an
    // unprotected market order.
    renderQuickTrade({ symbol: "NIFTY", exchange: "NSE" });
    await screen.findByText(/Qty: 1 × 1 = 1/);
    fireEvent.click(screen.getByRole("button", { name: /LIMIT/i }));
    fireEvent.click(screen.getByRole("button", { name: /buy 1 lot /i }));
    await waitFor(() => {
      expect(screen.getByText(/price above zero/i)).toBeTruthy();
    });
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("sends a LIMIT order once a real price is entered", async () => {
    renderQuickTrade({ symbol: "NIFTY", exchange: "NSE" });
    await screen.findByText(/Qty: 1 × 1 = 1/);
    fireEvent.click(screen.getByRole("button", { name: /LIMIT/i }));
    fireEvent.change(screen.getByPlaceholderText("0.00"), {
      target: { value: "22150.5" },
    });
    fireEvent.click(screen.getByRole("button", { name: /buy 1 lot /i }));
    await waitFor(() => {
      expect(mockPlaceOrder).toHaveBeenCalledWith(
        expect.objectContaining({ orderType: "LIMIT", price: 22150.5 }),
      );
    });
  });
});
