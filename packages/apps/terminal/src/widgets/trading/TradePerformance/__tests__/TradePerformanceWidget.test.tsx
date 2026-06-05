import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/services/ftApi", () => ({
  getTradeJournal: vi.fn(() => Promise.resolve({ trades: [], total: 0 })),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getTradeJournal, type JournalTrade } from "@/services/ftApi";
import TradePerformanceWidget, { journalToRecords } from "../TradePerformanceWidget";

const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockJournal = getTradeJournal as ReturnType<typeof vi.fn>;

/** Render with a fresh, retry-disabled QueryClient (the widget uses useQuery). */
function renderWidget(ui: ReactElement = <TradePerformanceWidget />) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  mockUseBrokerConnected.mockReturnValue(false);
  mockJournal.mockReset();
  mockJournal.mockResolvedValue({ trades: [], total: 0 });
});

describe("TradePerformanceWidget", () => {
  it("renders the widget title", () => {
    renderWidget();
    expect(screen.getByText("Trade Performance")).toBeTruthy();
  });

  it("shows Sample badge when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("hides Sample badge when connected", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    renderWidget();
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("renders the equity curve SVG", () => {
    renderWidget();
    expect(screen.getByRole("img", { name: /equity curve chart/i })).toBeTruthy();
  });

  it("uses the shared core threshold-line chart for the equity curve", () => {
    renderWidget();
    const chart = screen.getByRole("img", { name: /equity curve chart/i });

    expect(chart).toHaveAttribute("data-flint-chart", "threshold-line");
    expect(chart.querySelector("polyline")).not.toBeInTheDocument();
  });

  it("renders key metrics section with Win Rate", () => {
    renderWidget();
    expect(screen.getByText("Win Rate")).toBeTruthy();
  });

  it("renders key metrics section with Profit Factor", () => {
    renderWidget();
    expect(screen.getByText("Profit Factor")).toBeTruthy();
  });

  it("renders streak tracker section", () => {
    renderWidget();
    expect(screen.getByText("Current")).toBeTruthy();
    expect(screen.getByText("Best Win")).toBeTruthy();
    expect(screen.getByText("Worst Loss")).toBeTruthy();
  });

  it("renders monthly returns heatmap with months", () => {
    renderWidget();
    expect(screen.getByLabelText("Monthly returns heatmap")).toBeTruthy();
  });

  it("renders day distribution chart", () => {
    renderWidget();
    expect(screen.getByRole("img", { name: /trade distribution by day/i })).toBeTruthy();
  });

  it("uses the shared core categorical bar chart for day distribution", () => {
    renderWidget();
    const chart = screen.getByRole("img", { name: /trade distribution by day/i });

    expect(chart).toHaveAttribute("data-flint-chart", "categorical-bar");
    expect(chart.querySelectorAll("[data-categorical-bar]").length).toBeGreaterThan(0);
  });

  it("renders Expectancy metric", () => {
    renderWidget();
    expect(screen.getByText("Expectancy")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// journalToRecords mapping (connected — only realised trades, no fabrication)
// ---------------------------------------------------------------------------

function jt(overrides: Partial<JournalTrade>): JournalTrade {
  return {
    timestamp: "2026-03-02T10:00:00+05:30", symbol: "X", exchange: "NSE",
    action: "BUY", quantity: 1, price: 1, pnl: 0, strategy: "manual",
    entry_price: 0, exit_price: 0, fees: 0, ...overrides,
  };
}

describe("journalToRecords", () => {
  it("excludes legs with no realised P&L (no fake break-evens)", () => {
    const rows = [jt({ pnl: 0 }), jt({ pnl: 1200 }), jt({ pnl: -300 })];
    const recs = journalToRecords(rows);
    expect(recs).toHaveLength(2);
  });

  it("marks positive P&L as a win and negative as a loss", () => {
    const recs = journalToRecords([jt({ pnl: 1200 }), jt({ pnl: -300 })]);
    expect(recs[0].isWin).toBe(true);
    expect(recs[1].isWin).toBe(false);
  });

  it("takes the date from the timestamp", () => {
    const recs = journalToRecords([jt({ timestamp: "2026-03-02T10:00:00+05:30", pnl: 5 })]);
    expect(recs[0].date).toBe("2026-03-02");
  });
});

describe("TradePerformanceWidget (connected)", () => {
  it("queries the journal when connected and not when disconnected", async () => {
    mockUseBrokerConnected.mockReturnValue(false);
    renderWidget();
    expect(mockJournal).not.toHaveBeenCalled();

    mockUseBrokerConnected.mockReturnValue(true);
    renderWidget();
    await vi.waitFor(() => expect(mockJournal).toHaveBeenCalled());
  });

  it("shows an honest empty state when connected with no realised trades", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockJournal.mockResolvedValue({ trades: [], total: 0 });
    renderWidget();
    expect(await screen.findByText(/No closed trades yet this year/i)).toBeTruthy();
  });

  it("renders metrics from real journal data when connected", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockJournal.mockResolvedValue({
      trades: [jt({ pnl: 1000 }), jt({ pnl: 2000 })],
      total: 2,
    });
    renderWidget();
    // 2 wins → 100% win rate tile renders (sample data would not be all-wins).
    expect(await screen.findByText("Win Rate")).toBeTruthy();
    expect(screen.getByText("100.0%")).toBeTruthy();
  });
});
