import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import TradeLogWidget, {
  SAMPLE_TRADES,
  computeStats,
} from "../TradeLogWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  // Mock URL.createObjectURL for CSV export tests
  global.URL.createObjectURL = vi.fn(() => "blob:mock");
  global.URL.revokeObjectURL = vi.fn();
});

// ---------------------------------------------------------------------------
// Widget render tests
// ---------------------------------------------------------------------------

describe("TradeLogWidget", () => {
  it("renders widget title", () => {
    mockConnected.mockReturnValue(false);
    render(<TradeLogWidget />);
    expect(screen.getByText("Trade Log")).toBeTruthy();
  });

  it("shows Sample badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<TradeLogWidget />);
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("does not show Sample badge when connected", () => {
    mockConnected.mockReturnValue(true);
    render(<TradeLogWidget />);
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("renders execution history table", () => {
    mockConnected.mockReturnValue(false);
    render(<TradeLogWidget />);
    expect(screen.getByLabelText("Execution history table")).toBeTruthy();
  });

  it("renders all column headers", () => {
    mockConnected.mockReturnValue(false);
    render(<TradeLogWidget />);
    expect(screen.getByText("Time")).toBeTruthy();
    expect(screen.getByText("Symbol")).toBeTruthy();
    expect(screen.getByText("Action")).toBeTruthy();
    expect(screen.getByText("Qty")).toBeTruthy();
    expect(screen.getByText("Price")).toBeTruthy();
    expect(screen.getByText("Status")).toBeTruthy();
    expect(screen.getByText("Strategy")).toBeTruthy();
  });

  it("renders trade log statistics footer", () => {
    mockConnected.mockReturnValue(false);
    render(<TradeLogWidget />);
    expect(screen.getByLabelText("Trade log statistics")).toBeTruthy();
    expect(screen.getByText("Filled")).toBeTruthy();
    expect(screen.getByText("Total P&L")).toBeTruthy();
    expect(screen.getByText("Avg Fill")).toBeTruthy();
  });

  it("renders CSV export button", () => {
    mockConnected.mockReturnValue(false);
    render(<TradeLogWidget />);
    expect(screen.getByLabelText("Export CSV")).toBeTruthy();
  });

  it("renders status filter pills", () => {
    mockConnected.mockReturnValue(false);
    render(<TradeLogWidget />);
    // Use getAllByText since "filled"/"rejected"/"cancelled" also appear in table rows
    expect(screen.getAllByText("filled").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("rejected").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("cancelled").length).toBeGreaterThanOrEqual(1);
    // "All" only appears in the filter pill
    expect(screen.getByText("All")).toBeTruthy();
  });

  it("filters by status when clicking pill", () => {
    mockConnected.mockReturnValue(false);
    render(<TradeLogWidget />);
    // Click the "rejected" button pill (aria-pressed attribute distinguishes it)
    const rejectedPills = screen.getAllByText("rejected");
    const rejectedBtn = rejectedPills.find(
      (el) => el.tagName.toLowerCase() === "button",
    );
    expect(rejectedBtn).toBeDefined();
    fireEvent.click(rejectedBtn!);
    const rejectedCount = SAMPLE_TRADES.filter((t) => t.status === "rejected").length;
    expect(screen.getByText(`${rejectedCount} orders`)).toBeTruthy();
  });

  it("symbol search filters rows", () => {
    mockConnected.mockReturnValue(false);
    render(<TradeLogWidget />);
    const input = screen.getByLabelText("Search symbol") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "FINNIFTY" } });
    const finniftyCount = SAMPLE_TRADES.filter((t) => t.symbol.toLowerCase().includes("finnifty")).length;
    expect(screen.getByText(`${finniftyCount} orders`)).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Sample data and computeStats tests
// ---------------------------------------------------------------------------

describe("SAMPLE_TRADES", () => {
  it("has at least 5 entries", () => {
    expect(SAMPLE_TRADES.length).toBeGreaterThanOrEqual(5);
  });

  it("all entries have unique ids", () => {
    const ids = SAMPLE_TRADES.map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("all statuses are valid", () => {
    const valid = ["filled", "rejected", "cancelled", "pending"];
    for (const e of SAMPLE_TRADES) {
      expect(valid).toContain(e.status);
    }
  });

  it("filled entries have non-null pnl", () => {
    for (const e of SAMPLE_TRADES.filter((t) => t.status === "filled")) {
      expect(e.pnl).not.toBeNull();
    }
  });

  it("rejected/cancelled entries have null pnl", () => {
    for (const e of SAMPLE_TRADES.filter((t) => t.status !== "filled")) {
      expect(e.pnl).toBeNull();
    }
  });

  it("all prices are positive", () => {
    for (const e of SAMPLE_TRADES) {
      expect(e.price).toBeGreaterThan(0);
    }
  });
});

describe("computeStats", () => {
  it("returns zero stats for empty array", () => {
    const stats = computeStats([]);
    expect(stats.totalFilled).toBe(0);
    expect(stats.avgFillTimeMs).toBe(0);
  });

  it("totalFilled counts only filled entries", () => {
    const stats = computeStats(SAMPLE_TRADES);
    const expected = SAMPLE_TRADES.filter((t) => t.status === "filled").length;
    expect(stats.totalFilled).toBe(expected);
  });

  it("avgFillTimeMs is positive when filled entries exist", () => {
    const stats = computeStats(SAMPLE_TRADES);
    expect(stats.avgFillTimeMs).toBeGreaterThan(0);
  });
});
