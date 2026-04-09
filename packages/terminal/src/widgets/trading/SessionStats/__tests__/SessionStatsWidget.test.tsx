import { describe, it, expect, vi, beforeAll } from "vitest";
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

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import SessionStatsWidget from "../SessionStatsWidget";
import {
  SAMPLE_SESSION_TRADES,
  SAMPLE_ORDER_SUMMARY,
} from "../SessionStatsWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

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

  it("shows Sample badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<SessionStatsWidget />);
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("does not show Sample badge when connected", () => {
    mockConnected.mockReturnValue(true);
    render(<SessionStatsWidget />);
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("renders session equity chart with aria label", () => {
    mockConnected.mockReturnValue(false);
    render(<SessionStatsWidget />);
    expect(screen.getByLabelText("Session equity curve")).toBeTruthy();
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
