/**
 * PerformanceTab tests — ported from the retired TradePerformance widget suite
 * plus the old Analytics tab semantics (merge 2.12). Pins:
 *   - only realised trades count (pnl null/0 excluded, never fabricated);
 *   - metrics route through lib/journalAnalytics (win rate, profit factor "∞"
 *     instead of the fork's fabricated 99);
 *   - the equity curve/streaks run over CHRONOLOGICALLY sorted trades (the
 *     journal endpoint returns newest-first);
 *   - the YTD window ends on the IST trading day, not the lagging UTC day;
 *   - shared Flint chart primitives (threshold-line equity, signed
 *     categorical-bar day-of-week).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/services/ftApi", () => ({
  getTradeJournal: vi.fn(() => Promise.resolve({ trades: [], total: 0 })),
}));

import { getTradeJournal, type JournalTrade } from "@/services/ftApi";
import { useModeStore } from "@/stores/modeStore";
import {
  PerformanceTab,
  closedChronological,
  computeEquitySeries,
  computeMonthlyReturns,
  ytdIstRange,
} from "../PerformanceTab";

const mockJournal = getTradeJournal as ReturnType<typeof vi.fn>;

/** Render with a fresh, retry-disabled QueryClient (the tab uses useQuery). */
function renderTab(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function jt(overrides: Partial<JournalTrade>): JournalTrade {
  return {
    timestamp: "2026-03-02T10:00:00+05:30", symbol: "X", exchange: "NSE",
    action: "BUY", quantity: 1, price: 1, pnl: 0, strategy: "manual",
    entry_price: 0, exit_price: 0, fees: 0, ...overrides,
  };
}

const RANGE_LABEL = "2026-03-01 → 2026-03-07";

beforeEach(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  useModeStore.setState({ mode: "live" });
  mockJournal.mockReset();
  mockJournal.mockResolvedValue({ trades: [], total: 0 });
});

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

describe("closedChronological", () => {
  it("excludes legs with no realised P&L (no fake break-evens)", () => {
    const rows = [jt({ pnl: 0 }), jt({ pnl: 1200 }), jt({ pnl: -300 })];
    expect(closedChronological(rows)).toHaveLength(2);
  });

  it("excludes open legs journalled with pnl null", () => {
    const rows = [jt({ pnl: null as unknown as number }), jt({ pnl: 500 })];
    expect(closedChronological(rows)).toHaveLength(1);
  });

  it("REGRESSION: sorts newest-first journal rows into chronological order", () => {
    // The retired widget computed streaks and the equity curve in array order;
    // the journal endpoint returns newest-first, so its equity ran backwards.
    const rows = [
      jt({ timestamp: "2026-03-04T10:00:00+05:30", pnl: 300 }),
      jt({ timestamp: "2026-03-02T10:00:00+05:30", pnl: -100 }),
      jt({ timestamp: "2026-03-03T10:00:00+05:30", pnl: 200 }),
    ];
    expect(closedChronological(rows).map((r) => r.pnl)).toEqual([-100, 200, 300]);
  });
});

describe("computeEquitySeries", () => {
  it("starts at zero and accumulates in order", () => {
    const closed = closedChronological([
      jt({ timestamp: "2026-03-02T10:00:00+05:30", pnl: 1000 }),
      jt({ timestamp: "2026-03-03T10:00:00+05:30", pnl: -400 }),
      jt({ timestamp: "2026-03-04T10:00:00+05:30", pnl: 600 }),
    ]);
    expect(computeEquitySeries(closed)).toEqual([0, 1000, 600, 1200]);
  });
});

describe("computeMonthlyReturns", () => {
  it("slices the month from the written timestamp (no re-zoning)", () => {
    const closed = [
      jt({ timestamp: "2026-01-15T10:00:00+05:30", pnl: 500 }),
      jt({ timestamp: "2026-01-20T10:00:00+05:30", pnl: -200 }),
      jt({ timestamp: "2026-02-03T10:00:00+05:30", pnl: 900 }),
    ];
    expect(computeMonthlyReturns(closed)).toEqual({ "2026-01": 300, "2026-02": 900 });
  });
});

describe("ytdIstRange", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("REGRESSION: ends the YTD window on the IST day, not the lagging UTC day", () => {
    // 2026-07-24 19:30 UTC is 01:00 IST on 25 July — the retired widget's
    // `toISOString().slice(0, 10)` end date still read the 24th here, so the
    // current session's trades fell outside its YTD query.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-24T19:30:00Z"));
    expect(ytdIstRange()).toEqual({ start: "2026-01-01", end: "2026-07-25" });
  });
});

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

describe("PerformanceTab", () => {
  it("renders the scope toggle with YTD as the default", () => {
    renderTab(<PerformanceTab trades={[]} rangeLabel={RANGE_LABEL} />);
    const ytd = screen.getByRole("button", { name: "YTD" });
    const range = screen.getByRole("button", { name: "Range" });
    expect(ytd).toHaveAttribute("aria-pressed", "true");
    expect(range).toHaveAttribute("aria-pressed", "false");
  });

  it("queries the YTD journal when live and shows an honest empty state", async () => {
    renderTab(<PerformanceTab trades={[]} rangeLabel={RANGE_LABEL} />);
    await vi.waitFor(() => expect(mockJournal).toHaveBeenCalled());
    expect(await screen.findByText(/No closed trades yet this year/i)).toBeTruthy();
  });

  it("never queries the backend in explore mode and renders the sample prop rows", () => {
    useModeStore.setState({ mode: "explore" });
    renderTab(
      <PerformanceTab
        trades={[jt({ pnl: 1000 }), jt({ pnl: -250, timestamp: "2026-03-03T10:00:00+05:30" })]}
        rangeLabel={RANGE_LABEL}
      />,
    );
    expect(mockJournal).not.toHaveBeenCalled();
    expect(screen.getByText("Win Rate")).toBeTruthy();
    expect(screen.getByText("50.0%")).toBeTruthy();
  });

  it("renders metrics from real journal data when connected", async () => {
    mockJournal.mockResolvedValue({
      trades: [jt({ pnl: 1000 }), jt({ pnl: 2000 })],
      total: 2,
    });
    renderTab(<PerformanceTab trades={[]} rangeLabel={RANGE_LABEL} />);
    // 2 wins → 100% win rate tile renders (sample data would not be all-wins).
    expect(await screen.findByText("100.0%")).toBeTruthy();
  });

  it("renders '∞' for an all-win profit factor instead of a fabricated 99", async () => {
    mockJournal.mockResolvedValue({
      trades: [jt({ pnl: 1000 }), jt({ pnl: 2000 })],
      total: 2,
    });
    renderTab(<PerformanceTab trades={[]} rangeLabel={RANGE_LABEL} />);
    expect(await screen.findByText("∞")).toBeTruthy();
    expect(screen.queryByText("99.00")).toBeNull();
  });

  it("pins R:R and expectancy against the signed avg-loss reconciliation", async () => {
    // avgWin (900+1500)/2 = 1200, |avgLoss| 300 → R:R 4.00 (profit factor is
    // 2400/300 = 8.00, so the two tiles stay distinguishable); expectancy =
    // (2/3)×1200 − (1/3)×300 = ₹700.
    mockJournal.mockResolvedValue({
      trades: [
        jt({ pnl: 900 }),
        jt({ pnl: 1500, timestamp: "2026-03-03T10:00:00+05:30" }),
        jt({ pnl: -300, timestamp: "2026-03-04T10:00:00+05:30" }),
      ],
      total: 3,
    });
    renderTab(<PerformanceTab trades={[]} rangeLabel={RANGE_LABEL} />);
    expect(await screen.findByText("4.00")).toBeTruthy();
    expect(screen.getByText("8.00")).toBeTruthy();
    expect(screen.getByText("Expectancy")).toBeTruthy();
    expect(screen.getByText("₹700")).toBeTruthy();
  });

  it("uses the shared core threshold-line chart for the equity curve", async () => {
    mockJournal.mockResolvedValue({ trades: [jt({ pnl: 1000 })], total: 1 });
    renderTab(<PerformanceTab trades={[]} rangeLabel={RANGE_LABEL} />);
    const chart = await screen.findByRole("img", { name: /equity curve chart/i });
    expect(chart).toHaveAttribute("data-flint-chart", "threshold-line");
    expect(chart.querySelector("polyline")).not.toBeInTheDocument();
  });

  it("renders the streak tracker section", async () => {
    mockJournal.mockResolvedValue({ trades: [jt({ pnl: 1000 })], total: 1 });
    renderTab(<PerformanceTab trades={[]} rangeLabel={RANGE_LABEL} />);
    expect(await screen.findByText("Current")).toBeTruthy();
    expect(screen.getByText("Best Win")).toBeTruthy();
    expect(screen.getByText("Worst Loss")).toBeTruthy();
  });

  it("renders the monthly returns heatmap", async () => {
    mockJournal.mockResolvedValue({ trades: [jt({ pnl: 1000 })], total: 1 });
    renderTab(<PerformanceTab trades={[]} rangeLabel={RANGE_LABEL} />);
    expect(await screen.findByLabelText("Monthly returns heatmap")).toBeTruthy();
  });

  it("renders P&L by day of week through the shared signed categorical bar", async () => {
    mockJournal.mockResolvedValue({ trades: [jt({ pnl: 1000 })], total: 1 });
    renderTab(<PerformanceTab trades={[]} rangeLabel={RANGE_LABEL} />);
    const chart = await screen.findByRole("img", { name: "Trade review P&L by day of week" });
    expect(chart).toHaveAttribute("data-flint-chart", "signed-categorical-bar");
  });

  it("renders the P&L by symbol list (absorbed Analytics tab)", async () => {
    mockJournal.mockResolvedValue({
      trades: [jt({ pnl: 1000, symbol: "NIFTY" })],
      total: 1,
    });
    renderTab(<PerformanceTab trades={[]} rangeLabel={RANGE_LABEL} />);
    expect(await screen.findByText("P&L by Symbol")).toBeTruthy();
    expect(screen.getAllByText("NIFTY").length).toBeGreaterThan(0);
  });

  it("switches to the tool's committed range without a second fetch", async () => {
    const user = userEvent.setup();
    renderTab(
      <PerformanceTab
        trades={[jt({ pnl: 800 })]}
        rangeLabel={RANGE_LABEL}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Range" }));

    expect(screen.getByText(RANGE_LABEL)).toBeTruthy();
    // Range scope reads the tool's shared query result (the trades prop).
    expect(screen.getByText("100.0%")).toBeTruthy();
  });

  it("shows a range-scoped empty state when the committed range has no closed trades", async () => {
    const user = userEvent.setup();
    renderTab(<PerformanceTab trades={[]} rangeLabel={RANGE_LABEL} />);
    await user.click(screen.getByRole("button", { name: "Range" }));
    expect(screen.getByText(/No closed trades in the selected range/i)).toBeTruthy();
  });
});
