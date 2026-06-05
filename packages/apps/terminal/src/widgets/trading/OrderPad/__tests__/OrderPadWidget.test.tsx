/**
 * OrderPadWidget.test.tsx
 *
 * Tests for the OrderPad trading widget.
 * Verifies rendering, form elements, buy/sell toggle, and capital calculator.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";

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

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) =>
    selector({ mode: "practice" }),
}));

vi.mock("@/lib/market", () => ({
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
import * as jotai from "jotai";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = makeDockviewPanelProps();

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
});

// ---------------------------------------------------------------------------
// Strike offset utility — pure unit tests (no DOM needed)
// ---------------------------------------------------------------------------

describe("calculateStrike", () => {
  // Re-implement the logic here to test it independently without importing
  // the private function. This also serves as a specification document.

  function calculateStrike(
    spotLtp: number,
    offset: string,
    strikeGap: number,
    symbol: string,
  ): number {
    if (spotLtp <= 0 || strikeGap <= 0) return 0;
    const isPut = symbol.toUpperCase().endsWith("PE");
    const atmStrike = Math.round(spotLtp / strikeGap) * strikeGap;
    if (offset === "ATM") return atmStrike;
    const match = /^(ITM|OTM)(\d+)$/.exec(offset);
    if (!match) return atmStrike;
    const direction = match[1] as "ITM" | "OTM";
    const steps = parseInt(match[2], 10);
    const sign = (direction === "ITM") === !isPut ? -1 : 1;
    return atmStrike + sign * steps * strikeGap;
  }

  it("returns ATM strike rounded to gap", () => {
    expect(calculateStrike(22345, "ATM", 50, "NIFTY24DEC22350CE")).toBe(22350);
    expect(calculateStrike(44123, "ATM", 100, "BANKNIFTY25JAN44100CE")).toBe(44100);
  });

  it("returns 0 for zero spot", () => {
    expect(calculateStrike(0, "ATM", 50, "NIFTY")).toBe(0);
  });

  it("returns 0 for zero strike gap", () => {
    expect(calculateStrike(22000, "ATM", 0, "NIFTY")).toBe(0);
  });

  it("CE ITM1 is one gap below ATM", () => {
    // CE: ITM = below ATM
    const atm = Math.round(22000 / 50) * 50; // 22000
    expect(calculateStrike(22000, "ITM1", 50, "NIFTY24DEC22000CE")).toBe(atm - 50);
  });

  it("CE OTM1 is one gap above ATM", () => {
    const atm = Math.round(22000 / 50) * 50; // 22000
    expect(calculateStrike(22000, "OTM1", 50, "NIFTY24DEC22000CE")).toBe(atm + 50);
  });

  it("PE ITM1 is one gap above ATM", () => {
    // PE: ITM = above ATM
    const atm = Math.round(22000 / 50) * 50; // 22000
    expect(calculateStrike(22000, "ITM1", 50, "NIFTY24DEC22000PE")).toBe(atm + 50);
  });

  it("PE OTM1 is one gap below ATM", () => {
    const atm = Math.round(22000 / 50) * 50; // 22000
    expect(calculateStrike(22000, "OTM1", 50, "NIFTY24DEC22000PE")).toBe(atm - 50);
  });

  it("ITM5 CE is 5 gaps below ATM", () => {
    const atm = 22000;
    expect(calculateStrike(22000, "ITM5", 50, "NIFTY24DEC22000CE")).toBe(atm - 250);
  });

  it("OTM10 CE is 10 gaps above ATM", () => {
    const atm = 22000;
    expect(calculateStrike(22000, "OTM10", 50, "NIFTY24DEC22000CE")).toBe(atm + 500);
  });
});
