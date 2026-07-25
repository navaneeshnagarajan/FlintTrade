import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

// Live sources: default to empty (→ disclosed sample fallback).
const mockTradebook = vi.fn();
const mockOrders = vi.fn();
vi.mock("@/hooks/useTradebook", () => ({
  useTradebook: () => mockTradebook() as unknown,
}));
vi.mock("@/hooks/useOrders", () => ({
  useOrders: () => mockOrders() as unknown,
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import SessionStatsWidget from "../SessionStatsWidget";
import {
  SAMPLE_SESSION_TRADES,
  SAMPLE_ORDER_SUMMARY,
} from "../SessionStatsWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockTradebook.mockReset();
  mockOrders.mockReset();
  mockTradebook.mockReturnValue({ data: [] });
  mockOrders.mockReturnValue({ data: [] });
});

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

// ---------------------------------------------------------------------------
// Widget render tests
// ---------------------------------------------------------------------------

describe("SessionStatsWidget", () => {
  it("renders widget title", () => {
    mockConnected.mockReturnValue(false);
    render(<SessionStatsWidget />);
    expect(screen.getByText("Session Stats")).toBeTruthy();
  });

  it("shows Sample data badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<SessionStatsWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("still shows Sample data badge when connected — no live endpoint yet", () => {
    // SessionStatsWidget's badge is unconditional (the in-widget comment
    // explains the previous disconnected-only version was misleading
    // once a broker connects but the backend route still doesn't exist).
    mockConnected.mockReturnValue(true);
    render(<SessionStatsWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("renders session equity chart through the shared Flint primitive", () => {
    mockConnected.mockReturnValue(false);
    render(<SessionStatsWidget />);
    const chart = screen.getByRole("img", { name: "Session equity curve" });
    expect(chart).toHaveAttribute("viewBox", "0 0 160 42");
    expect(chart.querySelector("polyline")).not.toBeInTheDocument();
    expect(chart.querySelector("line")).toBeInTheDocument();
    expect(chart.querySelectorAll("path").length).toBeGreaterThan(0);
  });

  it("renders orders section with counts", () => {
    mockConnected.mockReturnValue(false);
    render(<SessionStatsWidget />);
    expect(screen.getByText("Placed")).toBeTruthy();
    expect(screen.getByText("Filled")).toBeTruthy();
    expect(screen.getByText("Rejected")).toBeTruthy();
    expect(screen.getByText("Pending")).toBeTruthy();
  });

  it("renders stats section headings", () => {
    mockConnected.mockReturnValue(false);
    render(<SessionStatsWidget />);
    expect(screen.getByText("Stats")).toBeTruthy();
    expect(screen.getByText(/Best \/ Worst Trade/i)).toBeTruthy();
    expect(screen.getByText("Time Breakdown")).toBeTruthy();
  });

  it("renders trade count, win rate, max drawdown tiles", () => {
    mockConnected.mockReturnValue(false);
    render(<SessionStatsWidget />);
    expect(screen.getByText("Trades")).toBeTruthy();
    expect(screen.getByText("Win Rate")).toBeTruthy();
    expect(screen.getByText("Max Drawdown")).toBeTruthy();
  });

  it("renders avg hold, active and idle tiles", () => {
    mockConnected.mockReturnValue(false);
    render(<SessionStatsWidget />);
    expect(screen.getByText("Avg Hold")).toBeTruthy();
    expect(screen.getByText("Active")).toBeTruthy();
    expect(screen.getByText("Idle")).toBeTruthy();
  });

  it("renders trade log table with column headers", () => {
    mockConnected.mockReturnValue(false);
    render(<SessionStatsWidget />);
    expect(screen.getByLabelText("Today's trade log")).toBeTruthy();
    expect(screen.getByText("Symbol")).toBeTruthy();
    expect(screen.getByText("Hold")).toBeTruthy();
  });

  it("renders all sample trades in the trade log", () => {
    mockConnected.mockReturnValue(false);
    render(<SessionStatsWidget />);
    for (const t of SAMPLE_SESSION_TRADES) {
      const timeEl = screen.getAllByText(t.entryTime);
      expect(timeEl.length).toBeGreaterThan(0);
    }
  });

  it("session total P&L is displayed in header", () => {
    mockConnected.mockReturnValue(false);
    render(<SessionStatsWidget />);
    // Total P&L from SAMPLE_SESSION_TRADES = 3240 - 1120 + 5680 - 890 + 2150 + 4410 - 620 = 12850
    const header = screen.getByLabelText("Session Stats widget");
    expect(header).toBeTruthy();
    // P&L element in header (profit)
    const pnlEl = header.querySelector(".text-profit, .text-loss");
    expect(pnlEl).toBeTruthy();
  });

  it("active vs idle bar is rendered", () => {
    mockConnected.mockReturnValue(false);
    render(<SessionStatsWidget />);
    expect(screen.getByLabelText("Active vs idle time bar")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Sample data tests
// ---------------------------------------------------------------------------

describe("SAMPLE_SESSION_TRADES", () => {
  it("has 7 trades", () => {
    expect(SAMPLE_SESSION_TRADES).toHaveLength(7);
  });

  it("all trades have positive holdMinutes", () => {
    for (const t of SAMPLE_SESSION_TRADES) {
      expect(t.holdMinutes).toBeGreaterThan(0);
    }
  });

  it("wins have positive pnl", () => {
    for (const t of SAMPLE_SESSION_TRADES.filter((t) => t.isWin)) {
      expect(t.pnl).toBeGreaterThan(0);
    }
  });

  it("losses have negative pnl", () => {
    for (const t of SAMPLE_SESSION_TRADES.filter((t) => !t.isWin)) {
      expect(t.pnl).toBeLessThan(0);
    }
  });

  it("all trades have non-empty symbol", () => {
    for (const t of SAMPLE_SESSION_TRADES) {
      expect(t.symbol.length).toBeGreaterThan(0);
    }
  });

  it("total session P&L is positive", () => {
    const total = SAMPLE_SESSION_TRADES.reduce((s, t) => s + t.pnl, 0);
    expect(total).toBeGreaterThan(0);
  });
});

describe("SAMPLE_ORDER_SUMMARY", () => {
  it("filled + rejected + pending equals placed", () => {
    const { placed, filled, rejected, pending } = SAMPLE_ORDER_SUMMARY;
    expect(filled + rejected + pending).toBe(placed);
  });

  it("filled count is the largest component", () => {
    const { filled, rejected, pending } = SAMPLE_ORDER_SUMMARY;
    expect(filled).toBeGreaterThan(rejected);
    expect(filled).toBeGreaterThan(pending);
  });
});


describe("SessionStatsWidget live mode", () => {
  it("computes stats from real closed round trips and badges Live", () => {
    mockTradebook.mockReturnValue({
      data: [
        { tradeId: "t1", orderId: "o1", symbol: "NIFTY24JUL24000CE", exchange: "NFO",
          action: "BUY", quantity: 75, price: 100, timestamp: "2026-07-19T09:20:00" },
        { tradeId: "t2", orderId: "o2", symbol: "NIFTY24JUL24000CE", exchange: "NFO",
          action: "SELL", quantity: 75, price: 110, timestamp: "2026-07-19T09:50:00" },
      ],
    });
    mockOrders.mockReturnValue({
      data: [
        { status: "complete" }, { status: "complete" }, { status: "rejected" }, { status: "open" },
      ],
    });
    render(<SessionStatsWidget />);
    expect(screen.getByText("Live")).toBeTruthy();
    expect(screen.queryByText("Sample data")).toBeNull();
    // One winning round trip: 75 × ₹10 = ₹750 (appears in header + tiles).
    expect(screen.getAllByText(/750/).length).toBeGreaterThan(0);
    expect(screen.getByText("1W / 0L")).toBeTruthy();
  });

  it("stays on the disclosed sample when fills exist but nothing closed", () => {
    mockTradebook.mockReturnValue({
      data: [
        { tradeId: "t1", orderId: "o1", symbol: "NIFTY24JUL24000CE", exchange: "NFO",
          action: "BUY", quantity: 75, price: 100, timestamp: "2026-07-19T09:20:00" },
      ],
    });
    render(<SessionStatsWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("shows the operator's real round trips in the trade log, never the sample rows", () => {
    // Regression: the trade log rendered SAMPLE_SESSION_TRADES unconditionally
    // while the header showed a Live badge — a connected operator saw seven
    // invented trades presented as today's fills.
    mockTradebook.mockReturnValue({
      data: [
        { tradeId: "t1", orderId: "o1", symbol: "BANKNIFTY24JUL52000PE", exchange: "NFO",
          action: "BUY", quantity: 15, price: 200, timestamp: "2026-07-19T10:00:00" },
        { tradeId: "t2", orderId: "o2", symbol: "BANKNIFTY24JUL52000PE", exchange: "NFO",
          action: "SELL", quantity: 15, price: 220, timestamp: "2026-07-19T10:30:00" },
      ],
    });
    render(<SessionStatsWidget />);

    const log = screen.getByLabelText("Today's trade log");
    expect(log.textContent).toContain("BANKNIFTY24JUL52000PE");
    // Not one of the invented sample symbols.
    for (const sample of SAMPLE_SESSION_TRADES) {
      expect(log.textContent).not.toContain(sample.symbol);
    }
  });
});
