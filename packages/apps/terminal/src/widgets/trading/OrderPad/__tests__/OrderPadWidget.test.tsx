/**
 * OrderPadWidget.test.tsx
 *
 * Tests for the OrderPad trading widget.
 * Verifies rendering, form elements, buy/sell toggle, and capital calculator.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/services/api", () => ({
  searchSymbol: vi.fn().mockResolvedValue([]),
  placeOrder: vi.fn().mockResolvedValue({ orderId: "TEST001" }),
  getSymbol: vi.fn().mockResolvedValue({ symbol: "NIFTY", exchange: "NSE", lotsize: 50, tick_size: 0.05 }),
}));

vi.mock("@/hooks/useMargin", () => ({
  useMargin: () => ({ data: null, isFetching: false }),
}));

vi.mock("@/hooks/useBrokerCapabilities", () => ({
  useBrokerCapabilities: () => ({ data: null }),
}));

const mockMode = vi.hoisted(() => ({ current: "practice" }));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) =>
    selector({ mode: mockMode.current }),
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
import { placeOrder, getSymbol } from "@/services/api";
import * as jotai from "jotai";

const mockPlaceOrder = vi.mocked(placeOrder);
const mockGetSymbol = vi.mocked(getSymbol);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = makeWidgetPanelProps();

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("OrderPadWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
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

  it("shows success toast after submitting a valid order", async () => {
    const { placeOrder } = await import("@/services/api");
    vi.mocked(placeOrder).mockResolvedValue({ orderId: "TEST001" });

    render(<OrderPadWidget {...defaultProps} />);

    // Submit the form — default values are valid (NIFTY, qty=1, MARKET)
    const submitBtn = screen.getByRole("button", { name: /practice buy/i });
    fireEvent.click(submitBtn);

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
    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));
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
    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));
    await screen.findByRole("alert");

    expect(placeOrder).toHaveBeenCalledWith(
      expect.objectContaining({ orderType: "MARKET", price: 250.5 }),
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

  it("shows the live premium hint on options exchanges", () => {
    vi.spyOn(jotai, "useAtomValue").mockReturnValue({ ltp: 623.45 });
    renderOptionsPad();

    expect(screen.getByText("Option Premium")).toBeInTheDocument();
    expect(screen.getByText(/Live premium ₹623.45/)).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));

    await vi.waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
    expect(mockPlaceOrder).toHaveBeenCalledWith(
      expect.objectContaining({ symbol: "NIFTY28MAR2422000CE", exchange: "NFO", quantity: 150 }),
    );
  });

  it("does not apply the lot constraint to equity exchanges", async () => {
    // Equity NSE with a failed symbol lookup — no lot constraint applies.
    mockGetSymbol.mockRejectedValue(new Error("lookup unavailable"));
    render(<OrderPadWidget {...defaultProps} />);

    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));

    await vi.waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
    expect(mockPlaceOrder).toHaveBeenCalledWith(
      expect.objectContaining({ exchange: "NSE", quantity: 1 }),
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

  it("refuses order entry in explore mode instead of relying on the backend 403", async () => {
    mockMode.current = "explore";
    render(<OrderPadWidget {...defaultProps} />);

    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));

    expect(await screen.findByText(/connect a broker to place orders/i)).toBeTruthy();
    expect(mockPlaceOrder).not.toHaveBeenCalled();
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

    const qtyInput = document.getElementById("orderpad-qty") as HTMLInputElement;
    fireEvent.change(qtyInput, { target: { value: "100" } });
    const discInput = document.getElementById("orderpad-disc-qty") as HTMLInputElement;
    fireEvent.change(discInput, { target: { value: "25" } });
    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));

    await vi.waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
    expect(mockPlaceOrder).toHaveBeenCalledWith(
      expect.objectContaining({ quantity: 100, disclosedQuantity: 25 }),
    );
  });

  it("omits the disclosed quantity when the operator leaves it blank", async () => {
    render(<OrderPadWidget {...defaultProps} />);

    fireEvent.click(screen.getByRole("button", { name: /practice buy/i }));

    await vi.waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
    expect(mockPlaceOrder.mock.calls[0][0]).not.toHaveProperty("disclosedQuantity");
  });
});
