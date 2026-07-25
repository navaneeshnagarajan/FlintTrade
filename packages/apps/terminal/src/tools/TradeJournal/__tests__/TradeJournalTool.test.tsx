/**
 * TradeJournalTool.test.tsx
 *
 * Tests for the Trade Journal canvas tool.
 * Verifies rendering, heading, and key UI elements.
 */

import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const tradeJournalMocks = vi.hoisted(() => ({
  queryOptions: undefined as { enabled?: boolean; queryKey?: unknown[] } | undefined,
  refetch: vi.fn(),
}));

// Mock TanStack Query. TradeLogTab (the default tab) runs its own
// ["journalScreenshots"] query + mutations, so the capture is keyed to the
// tool's ["tradeJournal", …] query and the mutation/client hooks are stubbed.
vi.mock("@tanstack/react-query", () => ({
  useQuery: (options: { enabled?: boolean; queryKey?: unknown[] }) => {
    if (options.queryKey?.[0] === "tradeJournal") {
      tradeJournalMocks.queryOptions = options;
    }
    return {
      data: undefined,
      isLoading: false,
      isError: false,
      refetch: tradeJournalMocks.refetch,
    };
  },
  useMutation: () => ({
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    isSuccess: false,
  }),
  useQueryClient: () => ({
    invalidateQueries: vi.fn(),
    setQueryData: vi.fn(),
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
    wins: 0,
    losses: 0,
    netPnl: 0,
    winRate: 0,
    avgWin: 0,
    avgLoss: 0,
    profitFactor: 0,
    bestTrade: 0,
    worstTrade: 0,
    byDayOfWeek: [],
    bySymbol: [],
    currentStreak: 0,
    streakType: "none",
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
  formatNumber: (v: number, digits = 0) => v.toFixed(digits),
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import TradeJournalTool from "../TradeJournalTool";
import { istDayKey, sevenDaysAgoISO, todayISO } from "../utils";
import { useModeStore } from "@/stores/modeStore";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TradeJournalTool", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    tradeJournalMocks.queryOptions = undefined;
    useModeStore.setState({ mode: "live" });
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

  it("keeps the backend journal query enabled outside explore mode", () => {
    render(<TradeJournalTool />);

    expect(tradeJournalMocks.queryOptions?.enabled).toBe(true);
    expect(screen.queryByText("Sample Data")).not.toBeInTheDocument();
  });

  it("renders sample trades in explore mode without enabling the backend query", () => {
    useModeStore.setState({ mode: "explore" });

    render(<TradeJournalTool />);

    expect(tradeJournalMocks.queryOptions?.enabled).toBe(false);
    expect(screen.getByText("Sample Data")).toBeInTheDocument();
    expect(screen.getAllByText("NIFTY").length).toBeGreaterThan(0);
  });

  it("filters explore sample trades through the strategy search", () => {
    useModeStore.setState({ mode: "explore" });

    render(<TradeJournalTool />);
    fireEvent.change(screen.getByLabelText("Strategy filter"), {
      target: { value: "VWAP" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(screen.getByText("Sample Data")).toBeInTheDocument();
    expect(screen.getAllByText("VWAP Reclaim").length).toBeGreaterThan(0);
    expect(screen.queryByText("Gap Fade")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Trade Review date range
//
// The range defaults must be Indian trading days: the journal rows the backend
// returns are keyed by IST session dates, so a UTC "today" silently drops the
// current session from the default window.
//
// Every case pins a FIXED instant. 2026-07-24 19:30 UTC is 01:00 IST on
// Saturday 25 July 2026 — inside the 00:00–05:29 IST window where the UTC date
// is still yesterday's, which is exactly what the old
// `new Date().toISOString().slice(0, 10)` returned.
// ---------------------------------------------------------------------------

const IST_EARLY_MORNING = new Date("2026-07-24T19:30:00Z");

describe("TradeJournalTool — IST date range defaults", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    tradeJournalMocks.queryOptions = undefined;
    useModeStore.setState({ mode: "live" });
    vi.useFakeTimers();
    vi.setSystemTime(IST_EARLY_MORNING);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("REGRESSION: defaults the range to IST days, not the UTC day", () => {
    // The UTC calendar still reads 24 July at this instant; India is on the
    // 25th. The old default end date was "2026-07-24", so a trade taken in the
    // small hours of the 25th fell outside the range the tool opened with.
    expect(IST_EARLY_MORNING.toISOString().slice(0, 10)).toBe("2026-07-24");

    render(<TradeJournalTool />);

    expect(screen.getByLabelText("End date")).toHaveValue("2026-07-25");
    expect(screen.getByLabelText("Start date")).toHaveValue("2026-07-19");
  });

  it("sends those same IST days to the backend query", () => {
    render(<TradeJournalTool />);

    expect(tradeJournalMocks.queryOptions?.queryKey).toEqual([
      "tradeJournal",
      "2026-07-19",
      "2026-07-25",
      "",
    ]);
  });

  it("spans seven IST calendar days inclusive of today", () => {
    expect(todayISO()).toBe("2026-07-25");
    expect(sevenDaysAgoISO()).toBe("2026-07-19");
  });

  it("keeps the range on the Indian calendar across a month boundary", () => {
    // 02:00 IST on 3 August 2026; UTC still reads 2 August.
    vi.setSystemTime(new Date("2026-08-02T20:30:00Z"));
    expect(todayISO()).toBe("2026-08-03");
    expect(sevenDaysAgoISO()).toBe("2026-07-28");
  });

  it("agrees with the notes-tab day key — one IST implementation, not two", () => {
    expect(todayISO()).toBe(istDayKey());
    expect(istDayKey(IST_EARLY_MORNING)).toBe("2026-07-25");
  });
});
