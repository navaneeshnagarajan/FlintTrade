/**
 * OrderPadWidget.test.tsx
 *
 * Tests for the OrderPad trading widget.
 * Verifies rendering, form elements, and buy/sell toggle.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
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

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------

import OrderPadWidget from "../OrderPadWidget";

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
});
