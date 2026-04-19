/**
 * ScalperWidget.test.tsx
 *
 * Tests for the Scalper trading widget.
 * Verifies rendering, CE/PE sections, and quantity controls.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/services/api", () => ({
  placeOrder: vi.fn().mockResolvedValue({}),
  cancelAllOrders: vi.fn().mockResolvedValue({}),
  closePosition: vi.fn().mockResolvedValue({}),
  getExpiry: vi.fn().mockResolvedValue(["2026-04-10", "2026-04-17"]),
  getQuotes: vi.fn().mockResolvedValue({ ltp: 24000 }),
}));

vi.mock("@/hooks/useWebSocket", () => ({
  default: () => ({ ticks: {} }),
}));

vi.mock("@/components/Chart", () => ({
  default: () => <div data-testid="mock-chart" />,
}));

// Mock radix Select to avoid complex portal/popover rendering in JSDOM
vi.mock("@/components/ui/select", () => ({
  Select: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: React.ReactNode }) => <button type="button">{children}</button>,
  SelectContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children, value }: { children: React.ReactNode; value: string }) => (
    <div data-value={value}>{children}</div>
  ),
  SelectValue: ({ placeholder }: { placeholder?: string }) => <span>{placeholder}</span>,
}));

// Mock AlertDialog similarly
vi.mock("@/components/ui/alert-dialog", () => ({
  AlertDialog: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AlertDialogAction: ({ children }: { children: React.ReactNode }) => <button type="button">{children}</button>,
  AlertDialogCancel: ({ children }: { children: React.ReactNode }) => <button type="button">{children}</button>,
  AlertDialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AlertDialogDescription: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AlertDialogFooter: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AlertDialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AlertDialogTitle: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------

import ScalperWidget from "../ScalperWidget";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = makeDockviewPanelProps();

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ScalperWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders without crashing", () => {
    const { container } = render(<ScalperWidget {...defaultProps} />);
    expect(container).toBeTruthy();
  });

  it("has CE section with Buy CE and Sell CE buttons", () => {
    render(<ScalperWidget {...defaultProps} />);

    expect(screen.getByText("Buy CE")).toBeInTheDocument();
    expect(screen.getByText("Sell CE")).toBeInTheDocument();
  });

  it("has PE section with Buy PE and Sell PE buttons", () => {
    render(<ScalperWidget {...defaultProps} />);

    expect(screen.getByText("Buy PE")).toBeInTheDocument();
    expect(screen.getByText("Sell PE")).toBeInTheDocument();
  });

  it("has lot quantity controls with increase/decrease buttons", () => {
    render(<ScalperWidget {...defaultProps} />);

    // The Lot stepper label should be present
    expect(screen.getByText("Lot")).toBeInTheDocument();

    // Increase/decrease buttons for Lot
    expect(screen.getByLabelText("Decrease Lot")).toBeInTheDocument();
    expect(screen.getByLabelText("Increase Lot")).toBeInTheDocument();
  });

  it("has CE Strike and PE Strike steppers", () => {
    render(<ScalperWidget {...defaultProps} />);

    expect(screen.getByText("CE Strike")).toBeInTheDocument();
    expect(screen.getByText("PE Strike")).toBeInTheDocument();

    expect(screen.getByLabelText("Decrease CE Strike")).toBeInTheDocument();
    expect(screen.getByLabelText("Increase CE Strike")).toBeInTheDocument();
    expect(screen.getByLabelText("Decrease PE Strike")).toBeInTheDocument();
    expect(screen.getByLabelText("Increase PE Strike")).toBeInTheDocument();
  });

  it("has Close All and Cancel All action buttons", () => {
    render(<ScalperWidget {...defaultProps} />);

    expect(screen.getByText("Close All")).toBeInTheDocument();
    expect(screen.getByText("Cancel All")).toBeInTheDocument();
  });

  // ── Interaction tests ────────────────────────────────────────────────────

  it("clicking 1-CLICK button toggles it to '1-CLICK ON' state", () => {
    render(<ScalperWidget {...defaultProps} />);

    // Initial state: one-click is OFF
    const toggleBtn = screen.getByTitle(/one-click off/i);
    expect(toggleBtn).toHaveTextContent("1-CLICK");

    fireEvent.click(toggleBtn);

    // After click: one-click is ON
    expect(screen.getByTitle(/one-click on/i)).toHaveTextContent("1-CLICK ON");
  });

  it("clicking 1-CLICK ON button toggles it back to OFF", () => {
    render(<ScalperWidget {...defaultProps} />);

    const toggleBtn = screen.getByTitle(/one-click off/i);
    fireEvent.click(toggleBtn);
    expect(screen.getByTitle(/one-click on/i)).toBeInTheDocument();

    // Click again to turn off
    fireEvent.click(screen.getByTitle(/one-click on/i));
    expect(screen.getByTitle(/one-click off/i)).toBeInTheDocument();
  });

  it("clicking Increase Lot increments the lot display span", () => {
    render(<ScalperWidget {...defaultProps} />);

    // The Lot Stepper renders the value as a <span> with text like "1 (50)"
    const increaseBtn = screen.getByLabelText("Increase Lot");
    const lotSpan = increaseBtn.closest("div")?.querySelector("span.font-mono") as HTMLElement;
    // Default lots = 1
    expect(lotSpan.textContent).toContain("1");

    fireEvent.click(increaseBtn);

    // After one click lots = 2
    expect(lotSpan.textContent).toContain("2");
  });

  it("clicking Decrease Lot when at minimum (1) keeps display at 1", () => {
    render(<ScalperWidget {...defaultProps} />);

    const decreaseBtn = screen.getByLabelText("Decrease Lot");
    const lotSpan = decreaseBtn.closest("div")?.querySelector("span.font-mono") as HTMLElement;

    // Default is 1; decrease is clamped by Math.max(1, l-1)
    fireEvent.click(decreaseBtn);
    expect(lotSpan.textContent).toContain("1");
  });
});
