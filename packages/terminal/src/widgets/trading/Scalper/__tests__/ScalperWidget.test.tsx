/**
 * ScalperWidget.test.tsx
 *
 * Tests for the Scalper trading widget.
 * Verifies rendering, CE/PE sections, and quantity controls.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

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

const defaultProps = {} as Parameters<typeof ScalperWidget>[0];

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
});
