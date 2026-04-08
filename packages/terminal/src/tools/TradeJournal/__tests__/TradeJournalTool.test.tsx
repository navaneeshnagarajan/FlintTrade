/**
 * TradeJournalTool.test.tsx
 *
 * Tests for the Trade Journal canvas tool.
 * Verifies rendering, heading, and key UI elements.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Mock TanStack Query
vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({
    data: undefined,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
}));

// Mock ft API
vi.mock("@/services/ftApi", () => ({
  getTradeJournal: vi.fn().mockResolvedValue({ trades: [] }),
}));

// Mock journal analytics
vi.mock("@/lib/journalAnalytics", () => ({
  computeAnalytics: () => ({
    totalTrades: 0,
    winners: 0,
    losers: 0,
    winRate: 0,
    avgWin: 0,
    avgLoss: 0,
    expectancy: 0,
    profitFactor: 0,
    totalPnl: 0,
    maxWin: 0,
    maxLoss: 0,
    avgRR: 0,
    dayOfWeekPnl: [],
  }),
  computeWeeklyWinRate: () => [],
  computeMonthlyWinRate: () => [],
  computeAvgPnlPerTrade: () => 0,
  computeDayPnl: () => [],
  getBestDays: () => [],
  getWorstDays: () => [],
  computeInstrumentPnl: () => [],
  computeHoldingTime: () => ({ avgMinutes: 0, minMinutes: 0, maxMinutes: 0 }),
  computeAllStreaks: () => [],
  getLongestWinStreak: () => 0,
  getLongestLossStreak: () => 0,
  computeRiskRewardDistribution: () => [],
}));

// Mock formatters
vi.mock("@/lib/formatters", () => ({
  formatCurrencyCompact: (v: number) => `₹${v}`,
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import TradeJournalTool from "../TradeJournalTool";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TradeJournalTool", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders without crashing", () => {
    const { container } = render(<TradeJournalTool />);
    expect(container).toBeInTheDocument();
  });

  it("shows the Trade Journal heading", () => {
    render(<TradeJournalTool />);
    expect(screen.getByText("Trade Journal")).toBeInTheDocument();
  });

  it("has date input placeholders for search filters", () => {
    render(<TradeJournalTool />);
    const dateInputs = screen.getAllByPlaceholderText("YYYY-MM-DD");
    expect(dateInputs.length).toBeGreaterThanOrEqual(2);
  });
});
