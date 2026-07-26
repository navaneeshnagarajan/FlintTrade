/**
 * CalendarTab tests — merge 2.12.
 *
 * Ports the P&L Dashboard calendar's IST pins (the ring and the future-greying
 * must read the Indian trading day, never the lagging UTC day) and the
 * HeatCalendar widget's surviving rendering pins (month navigation, legend),
 * over REAL journalled data via lib/journalAnalytics.computeDayPnl — including
 * the regression that an IST early-morning fill lands in the IST day's cell.
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
import { CalendarTab, monthWindow, heatmapColor } from "../CalendarTab";

const mockJournal = getTradeJournal as ReturnType<typeof vi.fn>;

function renderTab(ui: ReactElement = <CalendarTab />) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function jt(overrides: Partial<JournalTrade>): JournalTrade {
  return {
    timestamp: "2026-07-10T10:00:00+05:30", symbol: "NIFTY", exchange: "NFO",
    action: "BUY", quantity: 50, price: 23000, pnl: 500, strategy: "manual",
    entry_price: 23000, exit_price: 23010, fees: 20, ...overrides,
  };
}

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

afterEach(() => {
  vi.useRealTimers();
});

async function openAt(now: string) {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date(now));
  renderTab();
  return userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

describe("monthWindow", () => {
  it("returns the three months ending at the anchor with the covering range", () => {
    const { months, start, end } = monthWindow(2026, 6); // anchor July 2026
    expect(months.map((m) => m.label)).toEqual(["May 26", "Jun 26", "Jul 26"]);
    expect(start).toBe("2026-05-01");
    expect(end).toBe("2026-07-31");
  });

  it("crosses the year boundary backwards", () => {
    const { months, start, end } = monthWindow(2026, 0); // anchor January 2026
    expect(months.map((m) => m.label)).toEqual(["Nov 25", "Dec 25", "Jan 26"]);
    expect(start).toBe("2025-11-01");
    expect(end).toBe("2026-01-31");
  });
});

describe("heatmapColor", () => {
  it("scales by ₹ magnitude relative to the window's largest day", () => {
    expect(heatmapColor(1000, 1000)).toBe("bg-emerald-600");
    expect(heatmapColor(500, 1000)).toBe("bg-emerald-700/80");
    expect(heatmapColor(100, 1000)).toBe("bg-emerald-900/60");
    expect(heatmapColor(-1000, 1000)).toBe("bg-red-600");
    expect(heatmapColor(-100, 1000)).toBe("bg-red-900/60");
    expect(heatmapColor(0, 1000)).toBe("bg-surface-elevated");
    expect(heatmapColor(5, 0)).toBe("bg-surface-elevated");
  });
});

// ---------------------------------------------------------------------------
// IST calendar semantics (ported from the P&L Dashboard calendar)
// ---------------------------------------------------------------------------

describe("CalendarTab — IST calendar heatmap", () => {
  it("REGRESSION: rings the IST day, not the lagging UTC day", async () => {
    // 2026-07-24 19:30 UTC is 01:00 IST on 25 July. The old
    // `today.toISOString().slice(0, 10)` read "2026-07-24" here, so the ring
    // sat on yesterday's cell for the whole IST early morning.
    await openAt("2026-07-24T19:30:00Z");

    const today = await screen.findByTitle("2026-07-25");
    expect(today.className).toContain("ring-1");
    expect(screen.getByTitle("2026-07-24").className).not.toContain("ring-1");
  });

  it("REGRESSION: does not grey out today as a future day", async () => {
    await openAt("2026-07-24T19:30:00Z");

    const today = await screen.findByTitle("2026-07-25");
    expect(today.className).not.toContain("text-text-disabled");
    // Tomorrow is still future, and yesterday is still past.
    expect(screen.getByTitle("2026-07-26").className).toContain("text-text-disabled");
    expect(screen.getByTitle("2026-07-24").className).not.toContain("text-text-disabled");
  });

  it("picks the three months from the IST calendar", async () => {
    // 02:00 IST on Saturday 1 August 2026 — UTC still reads 31 July, so a
    // UTC/local month read shows May–July and never opens the August grid the
    // operator is actually trading.
    await openAt("2026-07-31T20:30:00Z");

    expect(await screen.findByText("Aug 26")).toBeInTheDocument();
    expect(screen.getByText("Jun 26")).toBeInTheDocument();
    expect(screen.queryByText("May 26")).not.toBeInTheDocument();
    expect(screen.getByTitle("2026-08-01").className).toContain("ring-1");
  });

  it("REGRESSION: buckets an IST early-morning fill under the IST day", async () => {
    // A fill journalled at 2026-07-24T19:30Z happened at 01:00 IST on the 25th.
    // The UTC-day bucketing this replaces filed it under the 24th.
    mockJournal.mockResolvedValue({
      trades: [jt({ timestamp: "2026-07-24T19:30:00.000Z", pnl: 750 })],
      total: 1,
    });
    await openAt("2026-07-25T10:00:00Z");

    const cell = await screen.findByTitle("2026-07-25: ₹750.00");
    expect(cell).toBeInTheDocument();
    expect(screen.getByTitle("2026-07-24")).toBeInTheDocument(); // no P&L on the 24th
  });
});

// ---------------------------------------------------------------------------
// Real-data rendering
// ---------------------------------------------------------------------------

describe("CalendarTab — journalled data", () => {
  it("colours cells from real daily P&L and totals the summary strip", async () => {
    mockJournal.mockResolvedValue({
      trades: [
        jt({ timestamp: "2026-07-10T10:00:00+05:30", pnl: 500 }),
        jt({ timestamp: "2026-07-13T10:00:00+05:30", pnl: -200 }),
      ],
      total: 2,
    });
    await openAt("2026-07-20T10:00:00Z");

    expect(await screen.findByTitle("2026-07-10: ₹500.00")).toBeInTheDocument();
    expect(screen.getByTitle("2026-07-13: -₹200.00")).toBeInTheDocument();
    expect(screen.getByText("Total P&L")).toBeInTheDocument();
    // ₹300.00 appears in the summary strip AND as the July month-card total.
    expect(screen.getAllByText("₹300.00").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Green Days")).toBeInTheDocument();
    expect(screen.getByText("Red Days")).toBeInTheDocument();
    expect(screen.getByText("Trading Days")).toBeInTheDocument();
  });

  it("shows a per-month total on each month card", async () => {
    mockJournal.mockResolvedValue({
      trades: [jt({ timestamp: "2026-07-10T10:00:00+05:30", pnl: 500 })],
      total: 1,
    });
    await openAt("2026-07-20T10:00:00Z");

    expect(
      await screen.findByLabelText("Jul 26 total P&L ₹500.00"),
    ).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Navigation + legend (ported from HeatCalendar)
// ---------------------------------------------------------------------------

describe("CalendarTab — navigation and legend", () => {
  it("renders previous and next month navigation buttons", async () => {
    await openAt("2026-07-20T10:00:00Z");
    expect(screen.getByRole("button", { name: /previous month/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /next month/i })).toBeInTheDocument();
  });

  it("navigates to the previous month window", async () => {
    const user = await openAt("2026-07-20T10:00:00Z");
    expect(screen.getByText("July 2026")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /previous month/i }));

    expect(screen.getByText("June 2026")).toBeInTheDocument();
    expect(await screen.findByText("Apr 26")).toBeInTheDocument();
    expect(screen.queryByText("Jul 26")).not.toBeInTheDocument();
  });

  it("renders the colour legend", async () => {
    await openAt("2026-07-20T10:00:00Z");
    expect(screen.getByText("Legend:")).toBeInTheDocument();
    expect(screen.getByText("Big loss")).toBeInTheDocument();
    expect(screen.getByText("Big profit")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Provenance
// ---------------------------------------------------------------------------

describe("CalendarTab — explore mode", () => {
  it("never queries the backend and badges the sample data", async () => {
    useModeStore.setState({ mode: "explore" });
    renderTab();

    expect(mockJournal).not.toHaveBeenCalled();
    const badge = screen.getByText("Sample data");
    expect(badge.getAttribute("role")).toBe("status");
    expect(badge.getAttribute("aria-label")).toMatch(/sample journal data/i);
  });
});
