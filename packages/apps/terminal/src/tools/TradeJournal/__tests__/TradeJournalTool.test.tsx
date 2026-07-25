/**
 * TradeJournalTool.test.tsx
 *
 * Tests for the Trade Review canvas tool (formerly "Trade Journal").
 * Verifies rendering, heading, the merged tab set (merge 2.12), and the IST
 * date-range defaults.
 */

import { describe, it, expect, vi, afterEach, beforeEach, beforeAll } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const tradeJournalMocks = vi.hoisted(() => ({
  queryOptions: undefined as { enabled?: boolean; queryKey?: unknown[] } | undefined,
  refetch: vi.fn(),
}));

// Mock TanStack Query. The capture is keyed to the tool's main
// ["tradeJournal", start, end, strategy] query (the four-element range key);
// the Calendar/Performance tabs run their own "tradeJournal"-rooted queries,
// but only when their tab content mounts, and their keys carry a marker
// segment — the guard below keeps the capture on the tool's range query.
vi.mock("@tanstack/react-query", () => ({
  useQuery: (options: { enabled?: boolean; queryKey?: unknown[] }) => {
    const key = options.queryKey ?? [];
    if (key[0] === "tradeJournal" && key.length === 4 && key[1] !== "perf" && key[1] !== "calendar") {
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

// The Log tab embeds the canonical Fills surface; stub it so this suite pins
// the tool wiring (the range handed over) without dragging in the Fills data
// planes, which have their own suite.
vi.mock("@/widgets/trading/Fills/FillsTable", () => ({
  FillsTable: ({ startDate, endDate }: { startDate?: string; endDate?: string }) => (
    <div data-testid="fills-table" data-start={startDate} data-end={endDate} />
  ),
}));

// Session-tab live sources (exercised via their own suite; stubbed empty here)
vi.mock("@/hooks/useTradebook", () => ({
  useTradebook: () => ({ data: [] }),
}));
vi.mock("@/hooks/useOrders", () => ({
  useOrders: () => ({ data: [] }),
}));
vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
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

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TradeJournalTool (Trade Review)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    tradeJournalMocks.queryOptions = undefined;
    useModeStore.setState({ mode: "live" });
  });

  it("renders without crashing", () => {
    const { container } = render(<TradeJournalTool />);
    expect(container).toBeInTheDocument();
  });

  it("shows the Trade Review heading (renamed from Trade Journal)", () => {
    render(<TradeJournalTool />);
    expect(screen.getByText("Trade Review")).toBeInTheDocument();
    expect(screen.queryByText("Trade Journal")).not.toBeInTheDocument();
  });

  it("labels the close control with the renamed identity", () => {
    render(<TradeJournalTool />);
    expect(screen.getByLabelText("Close trade review")).toBeInTheDocument();
  });

  it("renders the merged tab set", () => {
    render(<TradeJournalTool />);
    for (const tab of ["Log", "Session", "Performance", "Calendar", "Deep Analytics", "Notes", "Coach"]) {
      expect(screen.getByRole("tab", { name: tab })).toBeInTheDocument();
    }
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
  });

  it("filters explore sample trades through the strategy search", () => {
    // The sample set carries 4 "VWAP Reclaim" trades (days 2 and 5 back) — all
    // inside the default 7-IST-day window whatever the host clock reads — and
    // no strategies matching "zzz". The count badge is the filter's output now
    // that the fills rows render inside the (stubbed) Fills surface.
    useModeStore.setState({ mode: "explore" });

    render(<TradeJournalTool />);
    fireEvent.change(screen.getByLabelText("Strategy filter"), {
      target: { value: "VWAP" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(screen.getByText("4 trades")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Strategy filter"), {
      target: { value: "zzz" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(screen.getByText("0 trades")).toBeInTheDocument();
  });

  it("mounts the Session tab with its provenance badge", async () => {
    render(<TradeJournalTool />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Session" }));

    expect(screen.getByText("Today's Session")).toBeInTheDocument();
    // Stubbed empty tradebook → no closed round trips → disclosed sample.
    expect(screen.getByText("Sample data")).toBeInTheDocument();
  });

  it("mounts the Performance tab with an honest empty state when live with no trades", async () => {
    render(<TradeJournalTool />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Performance" }));

    expect(screen.getByText(/No closed trades yet this year/i)).toBeInTheDocument();
  });

  it("mounts the Calendar tab with month navigation", async () => {
    render(<TradeJournalTool />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Calendar" }));

    expect(screen.getByText("Daily P&L Calendar")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /previous month/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /next month/i })).toBeInTheDocument();
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

  it("hands the committed IST range to the embedded Fills log", () => {
    render(<TradeJournalTool />);

    const fills = screen.getByTestId("fills-table");
    expect(fills).toHaveAttribute("data-start", "2026-07-19");
    expect(fills).toHaveAttribute("data-end", "2026-07-25");
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
