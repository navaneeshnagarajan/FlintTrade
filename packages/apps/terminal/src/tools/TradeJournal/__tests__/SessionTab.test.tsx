/**
 * SessionTab tests — ported from the retired SessionStats widget suite
 * (merge 2.12). Every provenance and numeric pin survives:
 *   - the disclosed sample renders only while no real round trip has closed;
 *   - live round trips route through lib/pnl FIFO pairing (75 × ₹10 = ₹750);
 *   - REGRESSION: the trade-log table never shows sample rows under a Live
 *     badge;
 *   - computeSessionMetrics semantics (absolute-₹ drawdown from the equity
 *     peak, session minutes from the 09:15 open).
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

// Live sources: default to empty (→ disclosed sample fallback). The option
// objects are captured so the explore-mode gating can be asserted.
const mockTradebook = vi.fn();
const mockOrders = vi.fn();
const tradebookOptions: Array<{ enabled?: boolean } | undefined> = [];
const ordersOptions: Array<{ enabled?: boolean } | undefined> = [];
vi.mock("@/hooks/useTradebook", () => ({
  useTradebook: (options?: { enabled?: boolean }) => {
    tradebookOptions.push(options);
    return mockTradebook() as unknown;
  },
}));
vi.mock("@/hooks/useOrders", () => ({
  useOrders: (options?: { enabled?: boolean }) => {
    ordersOptions.push(options);
    return mockOrders() as unknown;
  },
}));

import { useModeStore } from "@/stores/modeStore";
import {
  SessionTab,
  SAMPLE_SESSION_TRADES,
  SAMPLE_ORDER_SUMMARY,
  computeSessionMetrics,
} from "../SessionTab";

beforeEach(() => {
  mockTradebook.mockReset();
  mockOrders.mockReset();
  tradebookOptions.length = 0;
  ordersOptions.length = 0;
  mockTradebook.mockReturnValue({ data: [] });
  mockOrders.mockReturnValue({ data: [] });
  useModeStore.setState({ mode: "live" });
});

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

// ---------------------------------------------------------------------------
// Render tests
// ---------------------------------------------------------------------------

describe("SessionTab", () => {
  it("renders the session heading", () => {
    render(<SessionTab />);
    expect(screen.getByText("Today's Session")).toBeTruthy();
  });

  it("shows the disclosed Sample data badge while no round trip has closed", () => {
    render(<SessionTab />);
    const badge = screen.getByText("Sample data");
    expect(badge).toBeTruthy();
    expect(badge.getAttribute("role")).toBe("status");
    expect(badge.getAttribute("aria-label")).toMatch(/sample data/i);
  });

  it("renders session equity chart through the shared Flint primitive", () => {
    render(<SessionTab />);
    const chart = screen.getByRole("img", { name: "Session equity curve" });
    expect(chart).toHaveAttribute("viewBox", "0 0 160 42");
    expect(chart.querySelector("polyline")).not.toBeInTheDocument();
    expect(chart.querySelector("line")).toBeInTheDocument();
    expect(chart.querySelectorAll("path").length).toBeGreaterThan(0);
  });

  it("renders orders section with counts", () => {
    render(<SessionTab />);
    expect(screen.getByText("Placed")).toBeTruthy();
    expect(screen.getByText("Filled")).toBeTruthy();
    expect(screen.getByText("Rejected")).toBeTruthy();
    expect(screen.getByText("Pending")).toBeTruthy();
  });

  it("renders stats section headings", () => {
    render(<SessionTab />);
    expect(screen.getByText("Stats")).toBeTruthy();
    expect(screen.getByText(/Best \/ Worst Trade/i)).toBeTruthy();
    expect(screen.getByText("Time Breakdown")).toBeTruthy();
  });

  it("renders trade count, win rate, max drawdown tiles", () => {
    render(<SessionTab />);
    expect(screen.getByText("Trades")).toBeTruthy();
    expect(screen.getByText("Win Rate")).toBeTruthy();
    expect(screen.getByText("Max Drawdown")).toBeTruthy();
  });

  it("renders avg hold, active and idle tiles", () => {
    render(<SessionTab />);
    expect(screen.getByText("Avg Hold")).toBeTruthy();
    expect(screen.getByText("Active")).toBeTruthy();
    expect(screen.getByText("Idle")).toBeTruthy();
  });

  it("renders trade log table with column headers", () => {
    render(<SessionTab />);
    expect(screen.getByLabelText("Today's trade log")).toBeTruthy();
    expect(screen.getByText("Symbol")).toBeTruthy();
    expect(screen.getByText("Hold")).toBeTruthy();
  });

  it("renders all sample trades in the trade log", () => {
    render(<SessionTab />);
    for (const t of SAMPLE_SESSION_TRADES) {
      const timeEl = screen.getAllByText(t.entryTime);
      expect(timeEl.length).toBeGreaterThan(0);
    }
  });

  it("displays the session total P&L in the status row", () => {
    render(<SessionTab />);
    // Total P&L from SAMPLE_SESSION_TRADES = 3240 - 1120 + 5680 - 890 + 2150 + 4410 - 620 = 12850
    const root = screen.getByLabelText("Session statistics");
    expect(root).toBeTruthy();
    const pnlEl = root.querySelector(".text-profit, .text-loss");
    expect(pnlEl).toBeTruthy();
  });

  it("active vs idle bar is rendered", () => {
    render(<SessionTab />);
    expect(screen.getByLabelText("Active vs idle time bar")).toBeTruthy();
  });

  it("disables the broker queries in explore mode and stays on the sample", () => {
    useModeStore.setState({ mode: "explore" });
    render(<SessionTab />);
    expect(tradebookOptions.every((o) => o?.enabled === false)).toBe(true);
    expect(ordersOptions.every((o) => o?.enabled === false)).toBe(true);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Sample data invariants
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

// ---------------------------------------------------------------------------
// computeSessionMetrics numeric pins
// ---------------------------------------------------------------------------

describe("computeSessionMetrics", () => {
  it("returns the empty-session shape with a full 375-minute session", () => {
    const m = computeSessionMetrics([]);
    expect(m.totalTrades).toBe(0);
    expect(m.totalPnl).toBe(0);
    expect(m.bestTrade).toBeNull();
    expect(m.worstTrade).toBeNull();
    expect(m.sessionMinutes).toBe(375);
  });

  it("pins the sample totals: ₹12,850 net, 4W/3L, drawdown ₹1,120", () => {
    const m = computeSessionMetrics(SAMPLE_SESSION_TRADES);
    expect(m.totalPnl).toBe(12850);
    expect(m.winCount).toBe(4);
    expect(m.lossCount).toBe(3);
    expect(m.winRate).toBeCloseTo((4 / 7) * 100, 5);
    // Absolute ₹ drawdown from the equity peak (equity dips 3240→2120 = 1120).
    expect(m.maxDrawdown).toBe(1120);
    expect(m.bestTrade?.pnl).toBe(5680);
    expect(m.worstTrade?.pnl).toBe(-1120);
  });

  it("measures the session from the 09:15 open to the last exit", () => {
    // Sample's last exit is 13:51 → (13×60+51) − (9×60+15) = 276 minutes.
    const m = computeSessionMetrics(SAMPLE_SESSION_TRADES);
    expect(m.sessionMinutes).toBe(276);
    expect(m.activeMinutes).toBe(SAMPLE_SESSION_TRADES.reduce((s, t) => s + t.holdMinutes, 0));
  });
});

// ---------------------------------------------------------------------------
// Live mode
// ---------------------------------------------------------------------------

describe("SessionTab live mode", () => {
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
    render(<SessionTab />);
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
    render(<SessionTab />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("shows the operator's real round trips in the trade log, never the sample rows", () => {
    // Regression: the retired widget's trade log rendered SAMPLE_SESSION_TRADES
    // unconditionally while the header showed a Live badge — a connected
    // operator saw seven invented trades presented as today's fills.
    mockTradebook.mockReturnValue({
      data: [
        { tradeId: "t1", orderId: "o1", symbol: "BANKNIFTY24JUL52000PE", exchange: "NFO",
          action: "BUY", quantity: 15, price: 200, timestamp: "2026-07-19T10:00:00" },
        { tradeId: "t2", orderId: "o2", symbol: "BANKNIFTY24JUL52000PE", exchange: "NFO",
          action: "SELL", quantity: 15, price: 220, timestamp: "2026-07-19T10:30:00" },
      ],
    });
    render(<SessionTab />);

    const log = screen.getByLabelText("Today's trade log");
    expect(log.textContent).toContain("BANKNIFTY24JUL52000PE");
    // Not one of the invented sample symbols.
    for (const sample of SAMPLE_SESSION_TRADES) {
      expect(log.textContent).not.toContain(sample.symbol);
    }
  });

  // The Orders bar has its own data source, so it needs its own provenance:
  // real closed round trips plus an empty order book used to render the sample
  // 14/12/1/1 counts underneath a green "Live" badge.
  it("badges the Orders bar when only the order book is unavailable", () => {
    mockTradebook.mockReturnValue({
      data: [
        { tradeId: "t1", orderId: "o1", symbol: "NIFTY24JUL24000CE", exchange: "NFO",
          action: "BUY", quantity: 75, price: 100, timestamp: "2026-07-19T09:20:00" },
        { tradeId: "t2", orderId: "o2", symbol: "NIFTY24JUL24000CE", exchange: "NFO",
          action: "SELL", quantity: 75, price: 110, timestamp: "2026-07-19T09:50:00" },
      ],
    });
    mockOrders.mockReturnValue({ data: [] });
    render(<SessionTab />);

    // The header stays Live — the trade metrics genuinely are.
    expect(screen.getByText("Live")).toBeTruthy();
    // But the Orders section discloses that its counts are not.
    expect(screen.getByLabelText(/sample order counts/i)).toBeTruthy();
  });

  it("shows no Orders badge when the order book is real", () => {
    mockTradebook.mockReturnValue({
      data: [
        { tradeId: "t1", orderId: "o1", symbol: "NIFTY24JUL24000CE", exchange: "NFO",
          action: "BUY", quantity: 75, price: 100, timestamp: "2026-07-19T09:20:00" },
        { tradeId: "t2", orderId: "o2", symbol: "NIFTY24JUL24000CE", exchange: "NFO",
          action: "SELL", quantity: 75, price: 110, timestamp: "2026-07-19T09:50:00" },
      ],
    });
    mockOrders.mockReturnValue({ data: [{ status: "complete" }, { status: "rejected" }] });
    render(<SessionTab />);

    expect(screen.getByText("Live")).toBeTruthy();
    expect(screen.queryByLabelText(/sample order counts/i)).toBeNull();
  });
});
