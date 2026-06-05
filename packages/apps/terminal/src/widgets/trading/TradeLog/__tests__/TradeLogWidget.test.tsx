import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";

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
import TradeLogWidget, {
  SAMPLE_TRADES,
  computeStats,
  journalToTradeLog,
} from "../TradeLogWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockJournal = getTradeJournal as ReturnType<typeof vi.fn>;

/** Render with a fresh, retry-disabled QueryClient (the widget uses useQuery). */
function renderWidget(ui: ReactElement = <TradeLogWidget />) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

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

beforeEach(() => {
  mockConnected.mockReturnValue(false);
  mockJournal.mockReset();
  mockJournal.mockResolvedValue({ trades: [], total: 0 });
});

// ---------------------------------------------------------------------------
// Widget render tests
// ---------------------------------------------------------------------------

describe("TradeLogWidget", () => {
  it("renders widget title", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText("Trade Log")).toBeTruthy();
  });

  it("shows Sample badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("does not show Sample badge when connected", () => {
    mockConnected.mockReturnValue(true);
    renderWidget();
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("renders execution history table", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByLabelText("Execution history table")).toBeTruthy();
  });

  it("renders all column headers", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
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
    renderWidget();
    expect(screen.getByLabelText("Trade log statistics")).toBeTruthy();
    expect(screen.getByText("Filled")).toBeTruthy();
    expect(screen.getByText("Total P&L")).toBeTruthy();
    expect(screen.getByText("Avg Fill")).toBeTruthy();
  });

  it("renders CSV export button", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByLabelText("Export CSV")).toBeTruthy();
  });

  it("renders status filter pills", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    // Use getAllByText since "filled"/"rejected"/"cancelled" also appear in table rows
    expect(screen.getAllByText("filled").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("rejected").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("cancelled").length).toBeGreaterThanOrEqual(1);
    // "All" only appears in the filter pill
    expect(screen.getByText("All")).toBeTruthy();
  });

  it("filters by status when clicking pill", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
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
    renderWidget();
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

  it("paired (default) halves P&L; non-paired sums directly", () => {
    const rows = [
      { id: "a", time: "", symbol: "X", action: "BUY" as const, qty: 1, price: 1, orderType: "—" as const, status: "filled" as const, strategy: "", pnl: 100, fillTimeMs: null },
      { id: "b", time: "", symbol: "X", action: "SELL" as const, qty: 1, price: 1, orderType: "—" as const, status: "filled" as const, strategy: "", pnl: 100, fillTimeMs: null },
    ];
    expect(computeStats(rows).totalPnl).toBe(100); // paired → /2
    expect(computeStats(rows, false).totalPnl).toBe(200); // journal → sum
  });
});

// ---------------------------------------------------------------------------
// journalToTradeLog mapping (connected mode — no fabricated fields)
// ---------------------------------------------------------------------------

const SAMPLE_JOURNAL: JournalTrade[] = [
  {
    timestamp: "2026-06-05T10:02:08+05:30", orderid: "OA-1", symbol: "BANKNIFTY FUT",
    exchange: "NFO", action: "BUY", quantity: 15, price: 48150, product: "MIS",
    pnl: 0, strategy: "manual", entry_price: 0, exit_price: 0, fees: 0,
  },
  {
    timestamp: "2026-06-05T10:48:55+05:30", orderid: "OA-2", symbol: "BANKNIFTY FUT",
    exchange: "NFO", action: "SELL", quantity: 15, price: 48525, product: "MIS",
    pnl: 5625, strategy: "manual", entry_price: 48150, exit_price: 48525, fees: 0,
  },
];

describe("journalToTradeLog", () => {
  it("marks every row as a filled fill (journal = executed trades)", () => {
    for (const e of journalToTradeLog(SAMPLE_JOURNAL)) {
      expect(e.status).toBe("filled");
    }
  });

  it("never fabricates order type or fill latency", () => {
    for (const e of journalToTradeLog(SAMPLE_JOURNAL)) {
      expect(e.orderType).toBe("—");
      expect(e.fillTimeMs).toBeNull();
    }
  });

  it("maps action, qty, price, strategy from the journal row", () => {
    const [buy, sell] = journalToTradeLog(SAMPLE_JOURNAL);
    expect(buy.action).toBe("BUY");
    expect(buy.qty).toBe(15);
    expect(sell.action).toBe("SELL");
    expect(sell.price).toBe(48525);
    expect(sell.strategy).toBe("manual");
  });

  it("uses the broker orderid as the row id", () => {
    expect(journalToTradeLog(SAMPLE_JOURNAL)[0].id).toBe("OA-1");
  });

  it("coerces a missing/non-numeric pnl to null", () => {
    const row = { ...SAMPLE_JOURNAL[0], pnl: undefined as unknown as number };
    expect(journalToTradeLog([row])[0].pnl).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Connected mode — real journal, never sample data
// ---------------------------------------------------------------------------

describe("TradeLogWidget (connected)", () => {
  it("renders real journal rows, not sample trades", async () => {
    mockConnected.mockReturnValue(true);
    mockJournal.mockResolvedValue({ trades: SAMPLE_JOURNAL, total: 2 });
    renderWidget();
    // Real symbol appears…
    expect(await screen.findAllByText("BANKNIFTY FUT")).toBeTruthy();
    // …and a sample-only symbol does not.
    expect(screen.queryByText("NIFTY 22200 CE")).toBeNull();
  });

  it("shows an honest empty state when no trades are journalled", async () => {
    mockConnected.mockReturnValue(true);
    mockJournal.mockResolvedValue({ trades: [], total: 0 });
    renderWidget();
    expect(await screen.findByText("No trades recorded yet today")).toBeTruthy();
  });

  it("queries the trade journal when connected", async () => {
    mockConnected.mockReturnValue(true);
    mockJournal.mockResolvedValue({ trades: [], total: 0 });
    renderWidget();
    await waitFor(() => expect(mockJournal).toHaveBeenCalled());
  });

  it("does not query the journal when disconnected", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(mockJournal).not.toHaveBeenCalled();
  });
});
