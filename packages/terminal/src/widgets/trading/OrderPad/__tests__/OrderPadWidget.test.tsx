/**
 * OrderPadWidget.test.tsx
 *
 * Tests for the OrderPad trading widget.
 * Verifies rendering, form elements, buy/sell toggle, and capital calculator.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/services/api", () => ({
  searchSymbol: vi.fn().mockResolvedValue([]),
  placeOrder: vi.fn().mockResolvedValue({ orderId: "TEST001" }),
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

const defaultProps = {} as Parameters<typeof OrderPadWidget>[0];

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

  it("renders the capital amount input", () => {
    render(<OrderPadWidget {...defaultProps} />);
    expect(screen.getByLabelText(/or enter amount/i)).toBeInTheDocument();
  });

  it("shows LTP unavailable message when LTP is zero and amount is entered", () => {
    // useAtomValue returns null → ltp === 0
    render(<OrderPadWidget {...defaultProps} />);

    const capitalInput = screen.getByLabelText(/or enter amount/i);
    fireEvent.change(capitalInput, { target: { value: "50000" } });

    expect(
      screen.getByText(/ltp unavailable/i),
    ).toBeInTheDocument();
  });

  it("calculates quantity from capital amount when LTP is available", () => {
    // Mock tick with LTP = 200
    vi.spyOn(jotai, "useAtomValue").mockReturnValue({ ltp: 200 });

    render(<OrderPadWidget {...defaultProps} />);

    const capitalInput = screen.getByLabelText(/or enter amount/i);
    fireEvent.change(capitalInput, { target: { value: "50000" } });

    // floor(50000 / 200) = 250
    expect(screen.getByText(/250 qty/i)).toBeInTheDocument();
  });

  it("shows 'Amount too small' when capital is less than one unit", () => {
    // Mock tick with LTP = 200
    vi.spyOn(jotai, "useAtomValue").mockReturnValue({ ltp: 200 });

    render(<OrderPadWidget {...defaultProps} />);

    const capitalInput = screen.getByLabelText(/or enter amount/i);
    // 100 / 200 = 0.5 → floor = 0 → too small
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
});
