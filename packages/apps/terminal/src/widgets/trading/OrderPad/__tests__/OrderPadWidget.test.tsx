/**
 * OrderPadWidget.test.tsx
 *
 * Tests for the OrderPad trading widget.
 * Verifies rendering, form elements, buy/sell toggle, and capital calculator.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within, act, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/services/api", () => {
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
    searchSymbol: vi.fn().mockResolvedValue([]),
    placeOrder: vi.fn().mockResolvedValue({ orderId: "TEST001" }),
    getSymbol: vi.fn().mockResolvedValue({ symbol: "NIFTY", exchange: "NSE", lotsize: 50, tick_size: 0.05 }),
    OrderApiError,
  };
});

vi.mock("@/hooks/useMargin", () => ({
  useMargin: () => ({ data: null, isFetching: false }),
}));

vi.mock("@/hooks/useBrokerCapabilities", () => ({
  useBrokerCapabilities: () => ({ data: null }),
}));

const mockOpenPositions = vi.hoisted(() => ({
  rows: [] as Array<{
    symbol: string;
    exchange: string;
    product: string;
    quantity: number;
    averagePrice: number;
    ltp: number;
    pnl: number;
    pnlPercent: number;
  }>,
}));

vi.mock("@/hooks/usePositions", () => ({
  usePositions: () => ({ data: mockOpenPositions.rows, isFetching: false }),
}));

const mockOpenOrders = vi.hoisted(() => ({
  rows: [] as Array<{
    symbol: string;
    exchange: string;
    product: string;
    action: "BUY" | "SELL";
    status: string;
  }>,
}));

vi.mock("@/hooks/useOrders", () => ({
  useOrders: () => ({ data: mockOpenOrders.rows, isFetching: false }),
}));

const mockMode = vi.hoisted(() => ({ current: "practice" }));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: Object.assign(
    (selector: (s: { mode: string }) => unknown) => selector({ mode: mockMode.current }),
    { getState: () => ({ mode: mockMode.current }) },
  ),
}));

vi.mock("@/lib/market", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/market")>()),
  isMarketHours: () => false,
}));

// Jotai atoms — default to null tick (no LTP) unless test overrides
vi.mock("jotai", async () => {
  const actual = await vi.importActual<typeof import("jotai")>("jotai");
  return {
    ...actual,
    useAtomValue: vi.fn(() => null),
  };
});

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------

import OrderPadWidget from "../OrderPadWidget";
import { OrderApiError, placeOrder, getSymbol, searchSymbol } from "@/services/api";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";
import * as jotai from "jotai";

const mockPlaceOrder = vi.mocked(placeOrder);
const mockGetSymbol = vi.mocked(getSymbol);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = makeWidgetPanelProps();

async function reviewAndConfirmPractice(buttonName: RegExp = /practice (buy|sell)/i): Promise<void> {
  fireEvent.click(screen.getByRole("button", { name: buttonName }));
  const confirm = await screen.findByRole("button", {
    name: /confirm (simulated practice|example) order/i,
  });
  fireEvent.click(confirm);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("OrderPadWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockMode.current = "practice";
    mockOpenPositions.rows = [];
    mockOpenOrders.rows = [];
    useOperatorSignalStore.setState({ decisionStatus: "ready" });
    mockPlaceOrder.mockReset();
    mockPlaceOrder.mockResolvedValue({ orderId: "TEST001" });
    mockGetSymbol.mockReset();
    mockGetSymbol.mockResolvedValue({
      symbol: "NIFTY",
      name: "Nifty 50",
      exchange: "NSE",
      instrumenttype: "INDEX",
      lotsize: 1,
      tick_size: 0.05,
    });
    // Default: no LTP available
    vi.spyOn(jotai, "useAtomValue").mockReturnValue(null);
  });

  it("renders without crashing", () => {
    const { container } = render(<OrderPadWidget {...defaultProps} />);
    expect(container.querySelector("[data-tour-target='order-pad']")).toBeInTheDocument();
  });

  it("displays the Order Pad header", () => {
    render(<OrderPadWidget {...defaultProps} />);

    expect(screen.getByText("Order Pad")).toBeInTheDocument();
  });

  it("has BUY and SELL radio buttons", () => {
    render(<OrderPadWidget {...defaultProps} />);

    const radioGroup = screen.getByRole("radiogroup", { name: /transaction type/i });
    expect(radioGroup).toBeInTheDocument();

    // BUY and SELL each appear in the radio group AND in the order summary preview
    expect(screen.getAllByText("BUY").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("SELL").length).toBeGreaterThanOrEqual(1);
  });

  it("has quantity and price fields", () => {
    render(<OrderPadWidget {...defaultProps} />);

    // Quantity label
    expect(screen.getByText("Quantity")).toBeInTheDocument();
    // Price label
    expect(screen.getByText("Price")).toBeInTheDocument();
  });

  it("shows submit button with Practice prefix in practice mode", () => {
    render(<OrderPadWidget {...defaultProps} />);

    // In practice mode with BUY as default action, button text is "Practice Buy"
    const submitButton = screen.getByRole("button", { name: /practice buy/i });
    expect(submitButton).toBeInTheDocument();
  });

  it("seeds symbol/exchange/action from launcher params (W2 prefill)", () => {
    // A watchlist quick-Sell opens the ticket prefilled — the side seeds to SELL.
    render(
      <OrderPadWidget
        {...makeWidgetPanelProps({
          params: { symbol: "RELIANCE", exchange: "NSE", action: "SELL" },
        })}
      />,
    );

    // Action seeded to SELL → submit button reads "Practice Sell".
    expect(screen.getByRole("button", { name: /practice sell/i })).toBeInTheDocument();
    // Symbol seeded into the search field.
    expect(screen.getByDisplayValue("RELIANCE")).toBeInTheDocument();
  });

  it("applies a watchlist prefill for this pad only", () => {
    render(<OrderPadWidget {...makeWidgetPanelProps({
      params: { symbol: "SBIN", exchange: "NSE", action: "BUY" },
      api: { id: "pad-1", updateParameters: () => {} },
    })} />);
    const input = screen.getByPlaceholderText("Search symbol…") as HTMLInputElement;
    expect(input.value).toBe("SBIN");

    act(() => {
      window.dispatchEvent(new CustomEvent("flinttrade:orderPadPrefill", {
        detail: { tabId: "other-pad", params: { symbol: "TCS", exchange: "NSE", action: "BUY" } },
      }));
    });
    expect(input.value).toBe("SBIN");

    act(() => {
      window.dispatchEvent(new CustomEvent("flinttrade:orderPadPrefill", {
        detail: { tabId: "pad-1", params: { symbol: "RELIANCE", exchange: "NSE", action: "SELL" } },
      }));
    });
    expect(input.value).toBe("RELIANCE");
  });

  it("reapplies the same quick-trade target when the event nonce changes", async () => {
    vi.mocked(searchSymbol).mockResolvedValue([{ symbol: "INFY", exchange: "NSE" }]);
    render(<OrderPadWidget {...makeWidgetPanelProps({
      api: { id: "pad-1", updateParameters: () => {} },
    })} />);

    act(() => {
      window.dispatchEvent(new CustomEvent("flinttrade:orderPadPrefill", {
        detail: {
          tabId: "pad-1",
          nonce: "trade-1",
          params: { symbol: "SBIN", exchange: "NSE", action: "BUY" },
        },
      }));
    });
    expect(screen.getByDisplayValue("SBIN")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /practice buy/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: "SELL" }));
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "INFY" } });
    fireEvent.click(await screen.findByRole("button", { name: /INFY/ }));
    expect(screen.getByDisplayValue("INFY")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /practice sell/i })).toBeInTheDocument();

    act(() => {
      window.dispatchEvent(new CustomEvent("flinttrade:orderPadPrefill", {
        detail: {
          tabId: "pad-1",
          nonce: "trade-2",
          params: { symbol: "SBIN", exchange: "NSE", action: "BUY" },
        },
      }));
    });
    expect(screen.getByDisplayValue("SBIN")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /practice buy/i })).toBeInTheDocument();
    expect(screen.queryByDisplayValue("INFY")).not.toBeInTheDocument();
  });

  it("Enter selects the typed symbol and does not submit the previous one", async () => {
    vi.mocked(searchSymbol).mockResolvedValue([{ symbol: "INFY", exchange: "NSE" }]);
    render(
      <OrderPadWidget
        {...makeWidgetPanelProps({
          params: { symbol: "NIFTY", exchange: "NSE", action: "BUY" },
        })}
      />,
    );

    const input = screen.getByPlaceholderText("Search symbol…");
    fireEvent.change(input, { target: { value: "INFY" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(screen.getByDisplayValue("INFY")).toBeInTheDocument());
    expect(mockPlaceOrder).not.toHaveBeenCalled();
    expect(screen.queryByText(/No match for INFY/)).not.toBeInTheDocument();
  });

  it("Enter shows no match and does not submit the previous symbol", async () => {
    vi.mocked(searchSymbol).mockResolvedValue([]);
    render(
      <OrderPadWidget
        {...makeWidgetPanelProps({
          params: { symbol: "NIFTY", exchange: "NSE", action: "BUY" },
        })}
      />,
    );

    const input = screen.getByPlaceholderText("Search symbol…");
    fireEvent.change(input, { target: { value: "ZZZNOT" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(await screen.findByText("No match for ZZZNOT")).toBeInTheDocument();
    expect(mockPlaceOrder).not.toHaveBeenCalled();
    expect(screen.getByDisplayValue("ZZZNOT")).toBeInTheDocument();
  });

  it("has order type pills (MARKET, LIMIT, SL, SL-M)", () => {
    render(<OrderPadWidget {...defaultProps} />);

    // MARKET appears in both the pill group and the order summary preview,
    // so use getAllByText for it. Others may also appear in the summary.
    expect(screen.getAllByText("MARKET").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("LIMIT").length).toBeGreaterThanOrEqual(1);
    // SL and SL-M appear only in their pill buttons
    expect(screen.getByRole("radio", { name: "SL" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "SL-M" })).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Capital-to-quantity calculator tests
  // -------------------------------------------------------------------------

  it("renders Fund toggle and switches to fund mode", () => {
    render(<OrderPadWidget {...defaultProps} />);
    const fundBtn = screen.getByRole("button", { name: /fund/i });
    expect(fundBtn).toBeTruthy();
    fireEvent.click(fundBtn);
    expect(screen.getByLabelText(/fund amount/i)).toBeInTheDocument();
  });

  it("shows LTP unavailable message when LTP is zero and fund amount is entered", () => {
    render(<OrderPadWidget {...defaultProps} />);
    fireEvent.click(screen.getByRole("button", { name: /fund/i }));

    const capitalInput = screen.getByLabelText(/fund amount/i);
    fireEvent.change(capitalInput, { target: { value: "50000" } });

    expect(screen.getByText(/ltp unavailable/i)).toBeInTheDocument();
  });

  it("calculates quantity from fund amount when LTP is available", () => {
    vi.spyOn(jotai, "useAtomValue").mockReturnValue({ ltp: 200 });
    render(<OrderPadWidget {...defaultProps} />);
    fireEvent.click(screen.getByRole("button", { name: /fund/i }));

    const capitalInput = screen.getByLabelText(/fund amount/i);
    fireEvent.change(capitalInput, { target: { value: "50000" } });

    // floor(50000 / 200) = 250
    expect(screen.getByText("250")).toBeInTheDocument();
  });

  it("shows 'amount too small' when fund value is less than one unit", () => {
    vi.spyOn(jotai, "useAtomValue").mockReturnValue({ ltp: 200 });
    render(<OrderPadWidget {...defaultProps} />);
    fireEvent.click(screen.getByRole("button", { name: /fund/i }));

    const capitalInput = screen.getByLabelText(/fund amount/i);
    fireEvent.change(capitalInput, { target: { value: "100" } });

    expect(screen.getByText(/amount too small/i)).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Interaction tests
  // -------------------------------------------------------------------------

  it("switches from BUY to SELL when SELL radio is clicked", () => {
    render(<OrderPadWidget {...defaultProps} />);

    // Default is BUY — submit button says "Practice Buy"
    expect(screen.getByRole("button", { name: /practice buy/i })).toBeInTheDocument();

    // Click the SELL radio button in the transaction type radiogroup
    const radioGroup = screen.getByRole("radiogroup", { name: /transaction type/i });
    const sellRadio = radioGroup.querySelector('[role="radio"][aria-checked="false"]') as HTMLElement;
    fireEvent.click(sellRadio);

    // Submit button should now say "Practice Sell"
    expect(screen.getByRole("button", { name: /practice sell/i })).toBeInTheDocument();
  });

  it("updates order summary when order type pill is changed to LIMIT", () => {
    render(<OrderPadWidget {...defaultProps} />);

    // Default order type is MARKET — visible in the order summary preview
    expect(screen.getAllByText("MARKET").length).toBeGreaterThanOrEqual(1);

    // Click the LIMIT pill (role=radio, name="LIMIT") inside the Order Type radiogroup
    const limitRadio = screen.getByRole("radio", { name: "LIMIT" });
    fireEvent.click(limitRadio);

    // Order summary preview should now show LIMIT
    expect(screen.getAllByText("LIMIT").length).toBeGreaterThanOrEqual(1);
    // MARKET should be aria-checked=false
    const marketRadio = screen.getByRole("radio", { name: "MARKET" });
    expect(marketRadio).toHaveAttribute("aria-checked", "false");
  });

  it("decreasing quantity below 1 is clamped by the stepper", () => {
    render(<OrderPadWidget {...defaultProps} />);

    // Default qty is 1; decrease button tries to go below min=1
    const decreaseBtn = screen.getByLabelText("Decrease Quantity");
    fireEvent.click(decreaseBtn);

    // The qty input should still be 1 (clamped at min)
    const qtyInput = decreaseBtn.closest("div")?.querySelector("input") as HTMLInputElement;
    expect(Number(qtyInput.value)).toBeGreaterThanOrEqual(1);
  });

  it("keeps the reason collapsed until the operator opens it", async () => {
    render(<OrderPadWidget {...defaultProps} />);
    await screen.findByText("Lot: 1");
    expect(screen.getByRole("button", { name: "Add a reason (optional)" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Add a reason (optional)")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add a reason (optional)" }));
    const note = screen.getByLabelText("Add a reason (optional)");
    expect(note.tagName).toBe("INPUT");
    expect(screen.getByRole("button", { name: /practice buy/i })).toBeEnabled();
  });

  it("sends the admission note with a practice place", async () => {
    render(<OrderPadWidget {...defaultProps} />);
    await screen.findByText("Lot: 1");
    fireEvent.click(screen.getByRole("button", { name: "Add a reason (optional)" }));
    fireEvent.change(screen.getByLabelText("Add a reason (optional)"), {
      target: { value: "Planned breakout" },
    });
    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));
    fireEvent.click(await screen.findByRole("button", {
      name: /confirm (simulated practice|example) order/i,
    }));
    expect(mockPlaceOrder).toHaveBeenCalledWith(
      expect.objectContaining({ rationale: "Planned breakout" }),
      expect.objectContaining({ mode: "practice" }),
    );
  });

  it("shows Laya denied under the confirm control and leaves it off", async () => {
    mockPlaceOrder.mockRejectedValue(new OrderApiError("Example cannot place orders.", 403, {
      code: "laya_denied",
      reason: "Example cannot place orders.",
      message: "Example cannot place orders.",
      limits: { max_quantity: 100 },
    }));
    render(<OrderPadWidget {...defaultProps} />);
    await screen.findByText("Lot: 1");
    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));
    const confirm = await screen.findByRole("button", {
      name: /confirm (simulated practice|example) order/i,
    });
    fireEvent.click(confirm);
    const denied = await screen.findByTestId("laya-denied");
    expect(denied).toHaveTextContent("Laya denied");
    expect(denied).toHaveTextContent("Example cannot place orders.");
    expect(denied).toHaveTextContent("Max quantity 100.");
    expect(confirm).toBeDisabled();
    expect(screen.queryByText(/Approved by Laya/)).not.toBeInTheDocument();
    expect(denied.textContent).not.toMatch(/llm/i);
  });

  it("clears a Laya denial when decision status changes and leaves confirm retryable", async () => {
    mockPlaceOrder.mockRejectedValue(new OrderApiError("Laya is Down. New orders are paused until it's Ready. You can still close positions.", 403, {
      code: "laya_denied",
      reason: "Laya is Down. New orders are paused until it's Ready. You can still close positions.",
      message: "Laya is Down. New orders are paused until it's Ready. You can still close positions.",      limits: { max_quantity: 100 },
    }));
    useOperatorSignalStore.setState({ decisionStatus: "down" });
    render(<OrderPadWidget {...defaultProps} />);
    await screen.findByText("Lot: 1");
    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));
    const confirm = await screen.findByRole("button", {
      name: /confirm (simulated practice|example) order/i,
    });
    fireEvent.click(confirm);
    expect(await screen.findByTestId("laya-denied")).toHaveTextContent(
      "Laya is Down. New orders are paused until it's Ready. You can still close positions.",
    );
    expect(screen.queryByTestId("laya-limits")).not.toBeInTheDocument();
    expect(screen.queryByText(/Max quantity/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Start the Laya model/)).not.toBeInTheDocument();
    expect(confirm).toBeDisabled();

    act(() => {
      useOperatorSignalStore.setState({ decisionStatus: "ready" });
    });

    expect(screen.queryByTestId("laya-denied")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /confirm (simulated practice|example) order/i })).toBeEnabled();
  });

  it("shows a clamp and does not place until Place N is clicked", async () => {
    const clamp = "Not placed. Laya allows up to 1.";
    mockPlaceOrder.mockRejectedValueOnce(new OrderApiError(clamp, 409, {
      code: "laya_clamp",
      message: clamp,
      applied_quantity: 1,
      limits: { max_quantity: 1 },
    }));
    render(<OrderPadWidget {...defaultProps} />);
    await screen.findByText("Lot: 1");
    const qty = screen.getByLabelText("Quantity") as HTMLInputElement;
    fireEvent.change(qty, { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));
    fireEvent.click(await screen.findByRole("button", {
      name: /confirm (simulated practice|example) order/i,
    }));
    expect(await screen.findByTestId("laya-clamp")).toHaveTextContent(clamp);
    expect(mockPlaceOrder).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/TEST001/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Place 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /confirm (simulated practice|example) order/i })).toBeDisabled();
    await vi.waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
    let releasePlaced: (value: { orderId: string }) => void = () => {};
    mockPlaceOrder.mockImplementationOnce(
      () => new Promise((resolve) => {
        releasePlaced = resolve;
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Place 1" }));
    const review = screen.getByRole("dialog");
    const quantityRow = within(review).getByText("Quantity").parentElement;
    expect(quantityRow).toHaveTextContent("1");
    expect(quantityRow).not.toHaveTextContent("4");
    releasePlaced({ orderId: "TEST001" });
    await vi.waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(2));
    expect(mockPlaceOrder).toHaveBeenLastCalledWith(
      expect.objectContaining({ quantity: 1, strategy: "FlintOrderPad" }),
      expect.objectContaining({ mode: "practice" }),
    );
  });

  it("cancels a clamp without placing", async () => {
    const clamp = "Not placed. Laya allows up to 1.";
    mockPlaceOrder.mockRejectedValueOnce(new OrderApiError(clamp, 409, {
      code: "laya_clamp",
      message: clamp,
      applied_quantity: 1,
      limits: { max_quantity: 1 },
    }));
    render(<OrderPadWidget {...defaultProps} />);
    await screen.findByText("Lot: 1");
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));
    fireEvent.click(await screen.findByRole("button", {
      name: /confirm (simulated practice|example) order/i,
    }));
    expect(await screen.findByTestId("laya-clamp")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(mockPlaceOrder).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/TEST001/)).not.toBeInTheDocument();
  });

  it("submits the desk Order Pad request with no note", async () => {
    render(<OrderPadWidget {...defaultProps} />);
    await screen.findByText("Lot: 1");
    expect(screen.getByRole("button", { name: "Add a reason (optional)" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Add a reason (optional)")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));
    fireEvent.click(await screen.findByRole("button", {
      name: /confirm (simulated practice|example) order/i,
    }));
    await vi.waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
    expect(mockPlaceOrder).toHaveBeenCalledWith(
      expect.objectContaining({
        strategy: "FlintOrderPad",
        orderType: "MARKET",
        quantity: 1,
        triggerPrice: 0,
        rationale: "",
      }),
      expect.objectContaining({ mode: "practice" }),
    );
    const params = mockPlaceOrder.mock.calls[0]?.[0];
    expect(params?.rationale).toBe("");
    expect(params).not.toHaveProperty("note");
  });

  it("caps Close at the open quantity and keeps it enabled while Laya is Down", async () => {
    mockMode.current = "live";
    useOperatorSignalStore.setState({ decisionStatus: "down" });
    mockOpenPositions.rows = [{
      symbol: "NIFTY",
      exchange: "NSE",
      product: "MIS",
      quantity: 4,
      averagePrice: 100,
      ltp: 101,
      pnl: 4,
      pnlPercent: 1,
    }];
    mockPlaceOrder.mockResolvedValue({ orderId: "CLOSE1" });
    render(<OrderPadWidget {...defaultProps} />);
    await screen.findByText("Lot: 1");

    expect(screen.getByRole("button", { name: /place buy order/i })).toBeDisabled();
    expect(screen.getByTestId("live-write-rectify")).toHaveTextContent(
      "Laya is Down. New orders are paused until it's Ready. You can still close positions.",
    );
    const close = screen.getByTestId("orderpad-close");
    expect(close).toBeEnabled();
    expect(close).toHaveTextContent("Close");

    fireEvent.click(screen.getByRole("radio", { name: "SELL" }));
    const qty = screen.getByLabelText("Quantity") as HTMLInputElement;
    fireEvent.change(qty, { target: { value: "10" } });
    expect(Number(qty.value)).toBe(4);
    fireEvent.click(screen.getByLabelText("Increase Quantity"));
    expect(Number((screen.getByLabelText("Quantity") as HTMLInputElement).value)).toBe(4);

    fireEvent.click(close);
    expect(screen.queryByRole("button", { name: /confirm/i })).not.toBeInTheDocument();
    expect(mockPlaceOrder).toHaveBeenCalledTimes(1);
    expect(mockPlaceOrder).toHaveBeenCalledWith(
      expect.objectContaining({
        symbol: "NIFTY",
        exchange: "NSE",
        action: "SELL",
        product: "MIS",
        quantity: 4,
      }),
      { mode: "live" },
      { exit: true },
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Closed. Exits are allowed while Laya is Down.",
    );
  });

  it("keeps Close as a reduce-only exit when the operator retries it", async () => {
    mockMode.current = "live";
    mockOpenPositions.rows = [{
      symbol: "NIFTY",
      exchange: "NSE",
      product: "MIS",
      quantity: 4,
      averagePrice: 100,
      ltp: 101,
      pnl: 4,
      pnlPercent: 1,
    }];
    mockPlaceOrder
      .mockRejectedValueOnce(new Error("Connection failed"))
      .mockResolvedValueOnce({ orderId: "CLOSE2" });
    render(<OrderPadWidget {...defaultProps} />);
    await screen.findByText("Lot: 1");
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "10" } });

    fireEvent.click(screen.getByTestId("orderpad-close"));
    expect(mockPlaceOrder).toHaveBeenCalledWith(
      expect.objectContaining({ action: "SELL", quantity: 4 }),
      { mode: "live" },
      { exit: true },
    );
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(mockPlaceOrder).toHaveBeenLastCalledWith(
      expect.objectContaining({ action: "SELL", quantity: 4 }),
      { mode: "live" },
      { exit: true },
    );
  });

  it("keeps GTT visible and disabled", async () => {
    render(<OrderPadWidget {...defaultProps} />);
    await screen.findByText("Lot: 1");
    const gtt = screen.getByRole("button", { name: "GTT" });
    expect(gtt).toBeDisabled();
    expect(gtt).toHaveAttribute("title", "GTT orders aren't supported right now.");
  });

  it("shows the GTT refusal when a stale client is rejected", async () => {
    mockPlaceOrder.mockRejectedValue(new OrderApiError("rejected", 422, {
      code: "gtt_unsupported",
      message: "Not placed. GTT orders aren't supported right now.",
    }));
    render(<OrderPadWidget {...defaultProps} />);
    await screen.findByText("Lot: 1");
    await reviewAndConfirmPractice(/practice buy/i);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Not placed. GTT orders aren't supported right now.",
    );
  });

  it("shows the unreadable-book exit refusal", async () => {
    mockPlaceOrder.mockRejectedValue(new OrderApiError("rejected", 409, {
      code: "exit_orders_unreadable",
      message: "Not placed. One exit at a time for NIFTY until your broker's orders load.",
    }));
    render(<OrderPadWidget {...defaultProps} />);
    await screen.findByText("Lot: 1");
    await reviewAndConfirmPractice(/practice buy/i);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Not placed. One exit at a time for NIFTY until your broker's orders load.",
    );
  });

  it("does not send Close while an exit for the contract is pending", async () => {
    mockOpenPositions.rows = [{
      symbol: "NIFTY",
      exchange: "NSE",
      product: "MIS",
      quantity: 4,
      averagePrice: 100,
      ltp: 101,
      pnl: 4,
      pnlPercent: 1,
    }];
    mockOpenOrders.rows = [{
      symbol: "NIFTY",
      exchange: "NSE",
      product: "MIS",
      action: "SELL",
      status: "OPEN",
    }];
    render(<OrderPadWidget {...defaultProps} />);
    await screen.findByText("Lot: 1");
    expect(screen.getByTestId("exit-already-pending")).toHaveTextContent(
      "Not placed. An exit for NIFTY is already pending. Wait for it to fill, or cancel it and try again.",
    );
    const close = screen.getByTestId("orderpad-close");
    expect(close).toBeDisabled();
    fireEvent.click(close);
    expect(mockPlaceOrder).not.toHaveBeenCalled();  });

  it("shows tighter Degraded limits without Blocked chrome", async () => {
    useOperatorSignalStore.setState({ decisionStatus: "degraded" });
    render(<OrderPadWidget {...defaultProps} />);
    const note = await screen.findByTestId("laya-degraded-limits");
    expect(note).toHaveTextContent("Laya Degraded — tighter limits");
    expect(note).not.toHaveTextContent("Blocked");
    expect(screen.getByRole("button", { name: /practice buy/i })).toBeEnabled();
  });

  it("shows success toast after submitting a valid order", async () => {
    const { placeOrder } = await import("@/services/api");
    vi.mocked(placeOrder).mockResolvedValue({ orderId: "TEST001" });

    render(<OrderPadWidget {...defaultProps} />);
    await screen.findByText("Lot: 1");

    // Practice requires an explicit review before the existing placement path.
    await reviewAndConfirmPractice(/practice buy/i);

    // Toast appears with order ID
    await screen.findByRole("alert");
    expect(screen.getByRole("alert")).toHaveTextContent(/TEST001/i);
  });

  it("emits an order notification to the central log on success", async () => {
    const { placeOrder } = await import("@/services/api");
    vi.mocked(placeOrder).mockResolvedValue({ orderId: "TEST001" });

    const listener = vi.fn();
    window.addEventListener("flinttrade:notify", listener);

    render(<OrderPadWidget {...defaultProps} />);
    await screen.findByText("Lot: 1");
    await reviewAndConfirmPractice(/practice buy/i);
    await screen.findByRole("alert");

    expect(listener).toHaveBeenCalled();
    const detail = (listener.mock.calls[0][0] as CustomEvent).detail;
    expect(detail.category).toBe("order");
    expect(detail.title).toMatch(/order placed/i);
    window.removeEventListener("flinttrade:notify", listener);
  });

  it("feeds the live LTP as the price for a Practice MARKET order", async () => {
    // The paper engine rejects a zero-price market fill (it would fabricate a
    // fill at 0.0), so a Practice MARKET order must carry the live LTP.
    vi.spyOn(jotai, "useAtomValue").mockReturnValue({ ltp: 250.5 });
    vi.mocked(placeOrder).mockResolvedValue({ orderId: "TEST001" });

    render(<OrderPadWidget {...defaultProps} />);
    await screen.findByText("Lot: 1");
    await reviewAndConfirmPractice(/practice buy/i);
    await screen.findByRole("alert");

    expect(placeOrder).toHaveBeenCalledWith(
      expect.objectContaining({ orderType: "MARKET", price: 250.5 }),
      { mode: "practice" },
    );
  });
});

// ---------------------------------------------------------------------------
// Options price prefill — the LIMIT/SL price must come from the option's own
// live premium, never from strike arithmetic. Regression for the bug where a
// strike-gap-rounded transform of the premium was written into the price
// field, producing economically absurd limit prices.
// ---------------------------------------------------------------------------

describe("OrderPadWidget options premium prefill", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockMode.current = "practice";
  });

  function renderOptionsPad(): void {
    render(
      <OrderPadWidget
        {...makeWidgetPanelProps({
          params: { symbol: "NIFTY28MAR2422000CE", exchange: "NFO" },
        })}
      />,
    );
  }

  it("prefills the LIMIT price with the option premium, not a strike-like value", () => {
    // Premium ₹623.45 — the old bug would have written 600/1600-style strike
    // numbers (gap-rounded ± offsets) into the price field.
    vi.spyOn(jotai, "useAtomValue").mockReturnValue({ ltp: 623.45 });
    renderOptionsPad();

    fireEvent.click(screen.getByRole("radio", { name: "LIMIT" }));

    const priceInput = document.getElementById("orderpad-price") as HTMLInputElement;
    expect(Number(priceInput.value)).toBe(623.45);
  });

  it("shows the sandbox premium hint on options exchanges in Practice", () => {
    mockMode.current = "practice";
    vi.spyOn(jotai, "useAtomValue").mockReturnValue({ ltp: 623.45 });
    renderOptionsPad();

    expect(screen.getByText("Option Premium")).toBeInTheDocument();
    expect(screen.getByText(/Sandbox premium ₹623.45/)).toBeInTheDocument();
  });

  it("labels Explore option premium as sample, not Live", () => {
    mockMode.current = "explore";
    vi.spyOn(jotai, "useAtomValue").mockReturnValue({ ltp: 623.45 });
    renderOptionsPad();

    expect(screen.getByText(/Example premium ₹623.45/)).toBeInTheDocument();
    expect(screen.queryByText(/Live premium/i)).not.toBeInTheDocument();
  });

  it("leaves the price empty and asks for manual entry when no premium is available", () => {
    vi.spyOn(jotai, "useAtomValue").mockReturnValue(null);
    renderOptionsPad();

    fireEvent.click(screen.getByRole("radio", { name: "LIMIT" }));

    const priceInput = document.getElementById("orderpad-price") as HTMLInputElement;
    expect(priceInput.value).toBe("");
    expect(screen.getByText(/enter the limit price manually/i)).toBeInTheDocument();
  });

  it("does not render the removed strike-offset selector", () => {
    vi.spyOn(jotai, "useAtomValue").mockReturnValue({ ltp: 623.45 });
    renderOptionsPad();

    expect(screen.queryByText("Strike Offset")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// F&O lot-multiple validation — quantity on derivative exchanges (NFO/BFO/
// MCX/CDS) must be a positive multiple of the instrument's lot size, and
// submission fails closed when the lot size is unknown for a derivative.
// ---------------------------------------------------------------------------

describe("OrderPadWidget F&O lot-size validation", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockMode.current = "practice";
    vi.spyOn(jotai, "useAtomValue").mockReturnValue(null);
    mockPlaceOrder.mockReset();
    mockPlaceOrder.mockResolvedValue({ orderId: "TEST001" });
    mockGetSymbol.mockReset();
  });

  function renderNfoPad(): void {
    render(
      <OrderPadWidget
        {...makeWidgetPanelProps({
          params: { symbol: "NIFTY28MAR2422000CE", exchange: "NFO" },
        })}
      />,
    );
  }

  it("blocks submission when the quantity is not a lot multiple on NFO", async () => {
    mockGetSymbol.mockResolvedValue({
      symbol: "NIFTY28MAR2422000CE", name: "NIFTY", exchange: "NFO",
      instrumenttype: "OPTIDX", lotsize: 75, tick_size: 0.05,
    });
    renderNfoPad();

    // Lot size loads asynchronously; qty auto-fills to one lot.
    await screen.findByText("Lot: 75");

    const qtyInput = document.getElementById("orderpad-qty") as HTMLInputElement;
    fireEvent.change(qtyInput, { target: { value: "100" } });
    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));

    const messages = await screen.findAllByText(/positive multiple of the lot size \(75\)/i);
    expect(messages.length).toBeGreaterThanOrEqual(1);
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("fails closed when the lot size is unknown for a derivative exchange", async () => {
    mockGetSymbol.mockRejectedValue(new Error("symbol not found"));
    renderNfoPad();

    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));

    const messages = await screen.findAllByText(/lot size unknown/i);
    expect(messages.length).toBeGreaterThanOrEqual(1);
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("submits when the quantity is an exact lot multiple", async () => {
    mockGetSymbol.mockResolvedValue({
      symbol: "NIFTY28MAR2422000CE", name: "NIFTY", exchange: "NFO",
      instrumenttype: "OPTIDX", lotsize: 75, tick_size: 0.05,
    });
    renderNfoPad();
    await screen.findByText("Lot: 75");

    const qtyInput = document.getElementById("orderpad-qty") as HTMLInputElement;
    fireEvent.change(qtyInput, { target: { value: "150" } });
    await reviewAndConfirmPractice(/practice buy/i);

    await vi.waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
    expect(mockPlaceOrder).toHaveBeenCalledWith(
      expect.objectContaining({ symbol: "NIFTY28MAR2422000CE", exchange: "NFO", quantity: 150 }),
      { mode: "practice" },
    );
  });

  it("does not apply the lot constraint to equity exchanges", async () => {
    // Equity NSE with a failed symbol lookup — no lot constraint applies.
    mockGetSymbol.mockRejectedValue(new Error("lookup unavailable"));
    render(<OrderPadWidget {...defaultProps} />);

    await reviewAndConfirmPractice(/practice buy/i);

    await vi.waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
    expect(mockPlaceOrder).toHaveBeenCalledWith(
      expect.objectContaining({ exchange: "NSE", quantity: 1 }),
      { mode: "practice" },
    );
  });
});

// ---------------------------------------------------------------------------
// Shared pre-trade guards (lib/orderGuards). The pad previously had no
// explore-mode block of its own, sent LIMIT orders with a ₹0 price, and
// discarded the disclosed quantity the operator typed.
// ---------------------------------------------------------------------------

describe("OrderPadWidget shared pre-trade guards", () => {
  beforeEach(() => {
    mockPlaceOrder.mockReset();
    mockPlaceOrder.mockResolvedValue({ orderId: "OP001" });
    mockGetSymbol.mockReset();
    mockGetSymbol.mockResolvedValue({
      symbol: "RELIANCE", name: "Reliance", exchange: "NSE",
      instrumenttype: "EQ", lotsize: 1, tick_size: 0.05,
    });
    mockMode.current = "practice";
  });

  it("opens the sample review from Explore Sample Buy without requiring a broker", async () => {
    mockMode.current = "explore";
    render(<OrderPadWidget {...defaultProps} />);

    expect(screen.getByRole("button", { name: /example buy/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /practice buy/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /example buy/i }));

    expect(await screen.findByRole("dialog", { name: /review example order/i })).toBeInTheDocument();
    expect(screen.queryByText(/connect a broker to place orders/i)).not.toBeInTheDocument();
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("confirms an Explore Sample Buy on the paper path, never as a live order", async () => {
    mockMode.current = "explore";
    mockPlaceOrder.mockResolvedValue({ orderId: "SAMPLE-EXPLORE" });
    render(<OrderPadWidget {...defaultProps} />);

    await reviewAndConfirmPractice(/example buy/i);

    await vi.waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
    expect(mockPlaceOrder).toHaveBeenCalledWith(
      expect.objectContaining({ symbol: "NIFTY", action: "BUY" }),
      { mode: "practice" },
    );
    expect(mockPlaceOrder.mock.calls[0][1]).not.toEqual({ mode: "live" });
    expect(await screen.findByRole("alert")).toHaveTextContent(/SAMPLE-EXPLORE/i);
  });

  it("refuses a LIMIT order with no price instead of sending it at zero", async () => {
    render(<OrderPadWidget {...defaultProps} />);

    fireEvent.click(screen.getByRole("radio", { name: "LIMIT" }));
    const priceInput = document.getElementById("orderpad-price") as HTMLInputElement;
    fireEvent.change(priceInput, { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));

    const messages = await screen.findAllByText(/price above zero/i);
    expect(messages.length).toBeGreaterThanOrEqual(1);
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("sends the disclosed quantity the operator typed", async () => {
    render(<OrderPadWidget {...defaultProps} />);
    await screen.findByText("Lot: 1");

    const qtyInput = document.getElementById("orderpad-qty") as HTMLInputElement;
    fireEvent.change(qtyInput, { target: { value: "100" } });
    const discInput = document.getElementById("orderpad-disc-qty") as HTMLInputElement;
    fireEvent.change(discInput, { target: { value: "25" } });
    await reviewAndConfirmPractice(/practice buy/i);

    await vi.waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
    expect(mockPlaceOrder).toHaveBeenCalledWith(
      expect.objectContaining({ quantity: 100, disclosedQuantity: 25 }),
      { mode: "practice" },
    );
  });

  it("omits the disclosed quantity when the operator leaves it blank", async () => {
    render(<OrderPadWidget {...defaultProps} />);

    await reviewAndConfirmPractice(/practice buy/i);

    await vi.waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
    expect(mockPlaceOrder.mock.calls[0][0]).not.toHaveProperty("disclosedQuantity");
  });
});

// ---------------------------------------------------------------------------
// Practice-only order review/confirm stage
// Distinct stage, not a generic dialog. Explicit instrument/side/type/qty/price/exposure.
// Simulated/no-broker copy. Edits/back invalidate. Final confirm revalidates mode+intent.
// Covers mode switch while open, double submit, stale intent (no native call), accessible labels.
// ---------------------------------------------------------------------------
describe("OrderPadWidget Practice review/confirm stage", () => {
  beforeEach(() => {
    useOperatorSignalStore.setState({ decisionStatus: "ready" });
    mockPlaceOrder.mockReset();
    mockPlaceOrder.mockResolvedValue({ orderId: "PRAC001" });
    mockGetSymbol.mockReset();
    mockGetSymbol.mockResolvedValue({
      symbol: "NIFTY",
      name: "Nifty",
      exchange: "NSE",
      instrumenttype: "EQ",
      lotsize: 1,
      tick_size: 0.05,
    });
    mockMode.current = "practice";
  });

  it("renders distinct Practice review stage with exact details and simulated/no-broker copy before any placement", async () => {
    vi.spyOn(jotai, "useAtomValue").mockReturnValue({ ltp: 250.5 });
    render(<OrderPadWidget {...defaultProps} />);

    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));

    const review = await screen.findByRole("dialog", { name: /review practice order/i });
    const reviewQueries = within(review);
    expect(reviewQueries.getByText("NIFTY · NSE")).toBeInTheDocument();
    expect(reviewQueries.getByText("BUY")).toBeInTheDocument();
    expect(reviewQueries.getByText("MARKET")).toBeInTheDocument();
    expect(reviewQueries.getByText("1")).toBeInTheDocument();
    expect(reviewQueries.getByText("₹250.50 (estimated fill)")).toBeInTheDocument();
    expect(reviewQueries.getByText("₹250.50")).toBeInTheDocument();
    expect(reviewQueries.getByText("Confirm places this simulated order.")).toBeInTheDocument();
    expect(reviewQueries.queryByText(/Explore records a sample fill/i)).not.toBeInTheDocument();
    expect(reviewQueries.queryByText(/sandboxengine/i)).not.toBeInTheDocument();
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("submits the exact reviewed snapshot only after final confirmation", async () => {
    vi.spyOn(jotai, "useAtomValue").mockReturnValue({ ltp: 250.5 });
    render(<OrderPadWidget {...defaultProps} />);

    await reviewAndConfirmPractice(/practice buy/i);

    await vi.waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
    expect(mockPlaceOrder).toHaveBeenCalledWith(
      {
        symbol: "NIFTY",
        exchange: "NSE",
        action: "BUY",
        product: "MIS",
        orderType: "MARKET",
        quantity: 1,
        price: 250.5,
        triggerPrice: 0,
        strategy: "FlintOrderPad",
        rationale: "",
      },
      { mode: "practice" },
    );
  });

  it("Back invalidates the review and a later edit requires a fresh review", async () => {
    render(<OrderPadWidget {...defaultProps} />);
    await vi.waitFor(() => expect((document.getElementById("orderpad-qty") as HTMLInputElement).value).toBe("1"));

    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));
    await screen.findByRole("dialog", { name: /review practice order/i });
    fireEvent.click(screen.getByRole("button", { name: "Back to edit" }));

    expect(screen.queryByRole("dialog", { name: /review practice order/i })).not.toBeInTheDocument();
    const qtyInput = document.getElementById("orderpad-qty") as HTMLInputElement;
    fireEvent.change(qtyInput, { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));

    const freshReview = await screen.findByRole("dialog", { name: /review practice order/i });
    expect(within(freshReview).getByText("3")).toBeInTheDocument();
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("invalidates an open review as soon as the form intent is edited", async () => {
    render(<OrderPadWidget {...defaultProps} />);
    await vi.waitFor(() => expect((document.getElementById("orderpad-qty") as HTMLInputElement).value).toBe("1"));

    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));
    await screen.findByRole("dialog", { name: /review practice order/i });
    fireEvent.change(document.getElementById("orderpad-qty") as HTMLInputElement, { target: { value: "2" } });

    await vi.waitFor(() => {
      expect(screen.queryByRole("dialog", { name: /review practice order/i })).not.toBeInTheDocument();
    });
    expect(screen.getByRole("alert")).toHaveTextContent(/order details changed/i);
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("invalidates an open review when the selected mode switches away from Practice", async () => {
    const props = makeWidgetPanelProps();
    const view = render(<OrderPadWidget {...props} />);
    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));
    await screen.findByRole("dialog", { name: /review practice order/i });

    mockMode.current = "live";
    view.rerender(<OrderPadWidget {...props} params={{ channel: "blue" }} />);

    await vi.waitFor(() => {
      expect(screen.queryByRole("dialog", { name: /review practice order/i })).not.toBeInTheDocument();
    });
    expect(screen.getByRole("alert")).toHaveTextContent(/mode changed/i);
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("re-queries mode at final confirm and blocks a switch React has not rendered yet", async () => {
    render(<OrderPadWidget {...defaultProps} />);
    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));
    const confirm = await screen.findByRole("button", { name: /confirm simulated practice order/i });

    mockMode.current = "live";
    fireEvent.click(confirm);

    expect(await screen.findByRole("alert")).toHaveTextContent(/mode changed/i);
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("pins Practice authority into placeOrder so a mid-flight mode flip cannot retarget Live", async () => {
    let resolveOrder!: (value: { orderId: string }) => void;
    mockPlaceOrder.mockImplementation(() => new Promise((resolve) => {
      resolveOrder = resolve;
    }));
    render(<OrderPadWidget {...defaultProps} />);
    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));
    const confirm = await screen.findByRole("button", { name: /confirm simulated practice order/i });

    fireEvent.click(confirm);
    await vi.waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
    expect(mockPlaceOrder).toHaveBeenCalledWith(
      expect.objectContaining({ symbol: "NIFTY", action: "BUY" }),
      { mode: "practice" },
    );

    mockMode.current = "live";
    await act(async () => {
      resolveOrder({ orderId: "PRAC-PIN" });
      await Promise.resolve();
    });
    expect(mockPlaceOrder).toHaveBeenCalledTimes(1);
  });

  it("does not leave a Practice review payload available for a later Live retry", async () => {
    const props = makeWidgetPanelProps();
    const view = render(<OrderPadWidget {...props} />);
    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));
    await screen.findByRole("dialog", { name: /review practice order/i });

    mockMode.current = "live";
    view.rerender(<OrderPadWidget {...props} params={{ channel: "blue" }} />);
    await vi.waitFor(() => {
      expect(screen.queryByRole("dialog", { name: /review practice order/i })).not.toBeInTheDocument();
    });

    // No placement occurred from the invalidated Practice review, and Live
    // must not inherit a Practice lastParams payload for toast retry.
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("blocks double confirmation while the sandbox request is in flight", async () => {
    let resolveOrder!: (value: { orderId: string }) => void;
    mockPlaceOrder.mockImplementation(() => new Promise((resolve) => {
      resolveOrder = resolve;
    }));
    render(<OrderPadWidget {...defaultProps} />);
    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));
    const confirm = await screen.findByRole("button", { name: /confirm simulated practice order/i });

    fireEvent.click(confirm);
    fireEvent.click(confirm);

    expect(mockPlaceOrder).toHaveBeenCalledTimes(1);
    expect(confirm).toBeDisabled();
    await act(async () => {
      resolveOrder({ orderId: "PRAC001" });
      await Promise.resolve();
    });
    expect(screen.queryByRole("dialog", { name: /review practice order/i })).not.toBeInTheDocument();
  });

  it("leaves the existing Live placement behaviour untouched and never opens Practice review", async () => {
    mockMode.current = "live";
    render(<OrderPadWidget {...defaultProps} />);

    fireEvent.click(screen.getByRole("button", { name: /place buy order/i }));

    await vi.waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
    expect(mockPlaceOrder).toHaveBeenCalledWith(
      expect.objectContaining({ symbol: "NIFTY", action: "BUY" }),
      { mode: "live" },
    );
    expect(screen.queryByRole("dialog", { name: /review practice order/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/connect a broker to place orders/i)).not.toBeInTheDocument();
  });
});
