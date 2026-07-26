/**
 * FillsWidget.test.tsx — union suite for the canonical Fills widget
 * (dedup merge 2.11).
 *
 * Coverage is the union of the three ancestor suites:
 *   - TradeBookWidget tests (rows, filter pills, error banner, broker gating);
 *   - TradeLogWidget tests (sample badge, search, stats footer, CSV,
 *     journal mapping honesty, connected-mode behaviour) — minus the /2
 *     halving pin, replaced by an explicit direct-sum (anti-halving) pin;
 *   - the Trade Journal tool's TradeLogTab suite (all 24 tests adapted):
 *     screenshots (stable + legacy keys, attach, view, remove), lazy per-id
 *     byte fetching, and the one-time legacy localStorage import.
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@testing-library/jest-dom";
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const runtime = { mode: "live" };
vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) =>
    selector({ mode: runtime.mode }),
}));

const mockRefetch = vi.fn();
const mockUseTradebook = vi.fn();
vi.mock("@/hooks/useTradebook", () => ({
  useTradebook: (...args: unknown[]) => mockUseTradebook(...args) as unknown,
}));

const mockUseAccountReadsEnabled = vi.fn();
vi.mock("@/hooks/useAccountReadsEnabled", () => ({
  useAccountReadsEnabled: () => mockUseAccountReadsEnabled() as boolean,
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

const mockJournal = vi.fn();
vi.mock("@/services/ftApi", () => ({
  getTradeJournal: (...args: unknown[]) => mockJournal(...args) as Promise<unknown>,
}));

const mockList = vi.fn();
const mockGet = vi.fn();
const mockAdd = vi.fn();
const mockDelete = vi.fn();
vi.mock("@/services/ftApi.journal", () => ({
  listJournalScreenshots: () => mockList() as Promise<unknown>,
  getJournalScreenshot: (id: string) => mockGet(id) as Promise<unknown>,
  addJournalScreenshot: (tradeKey: string, dataUrl: string) =>
    mockAdd(tradeKey, dataUrl) as Promise<unknown>,
  deleteJournalScreenshot: (id: string) => mockDelete(id) as Promise<unknown>,
}));

// Radix portals do not play well with jsdom — same stub the TradeLogTab
// suite used.
vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({ children, open }: { children: React.ReactNode; open: boolean }) =>
    open ? <div role="dialog">{children}</div> : null,
  DialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
}));

// ---------------------------------------------------------------------------
// localStorage mock
// ---------------------------------------------------------------------------

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
    key: (i: number) => Object.keys(store)[i] ?? null,
    get length() { return Object.keys(store).length; },
  };
})();
Object.defineProperty(window, "localStorage", { value: localStorageMock });

// ---------------------------------------------------------------------------
// Imports under test
// ---------------------------------------------------------------------------

import type { JournalTrade } from "@/services/ftApi";
import FillsWidget from "../FillsWidget";
import { FillsTable } from "../FillsTable";
import {
  buildFillRows,
  computeFillStats,
  fillsToCsv,
  journalToFills,
  SAMPLE_FILLS,
  stableTradeKey,
  type RawFillSource,
} from "../fillsModel";

// ---------------------------------------------------------------------------
// Fixtures + helpers
// ---------------------------------------------------------------------------

const SCREENSHOTS_KEY = "flinttrade_journal_screenshots";
const FAKE_DATA_URL = "data:image/png;base64,iVBORw0KGgo=";

function queryResult(overrides: Record<string, unknown> = {}) {
  return {
    data: undefined as unknown,
    isLoading: false,
    isPending: false,
    isError: false,
    error: null as Error | null,
    isFetching: false,
    refetch: mockRefetch,
    dataUpdatedAt: 0,
    ...overrides,
  };
}

const BOOK_TRADES: RawFillSource[] = [
  {
    symbol: "NIFTY24APR23000CE", action: "BUY", quantity: "50",
    average_price: "150.00", trade_time: "2026-04-08T10:30:00+05:30", orderid: "OB-100",
  },
  {
    symbol: "NIFTY24APR23000PE", action: "SELL", quantity: "25",
    average_price: "80.00", trade_time: "2026-04-08T10:35:00+05:30", orderid: "OB-101",
  },
  {
    symbol: "BANKNIFTY24APR50000CE", action: "BUY", quantity: "15",
    average_price: "200.00", trade_time: "2026-04-08T11:00:00+05:30", orderid: "OB-102",
  },
];

const JOURNAL_TRADES: JournalTrade[] = [
  {
    timestamp: "2026-06-05T10:02:08+05:30", orderid: "OA-1", symbol: "BANKNIFTY FUT",
    exchange: "NFO", action: "BUY", quantity: 15, price: 48150, product: "MIS",
    pnl: 0, strategy: "manual", entry_price: 0, exit_price: 0, fees: 0,
  },
  {
    timestamp: "2026-06-05T10:48:55+05:30", orderid: "OA-2", symbol: "BANKNIFTY FUT",
    exchange: "NFO", action: "SELL", quantity: 15, price: 48525, product: "MIS",
    pnl: 5625, strategy: "manual", entry_price: 48150, exit_price: 48525, fees: 12.5,
  },
];

function makeTrade(overrides: Partial<JournalTrade> = {}): JournalTrade {
  return {
    timestamp: "2026-04-13T09:30:00",
    symbol: "NIFTY",
    exchange: "NFO",
    action: "BUY",
    quantity: 50,
    price: 22000,
    entry_price: 22000,
    exit_price: 22150,
    pnl: 7500,
    fees: 45,
    strategy: "TestStrategy",
    ...overrides,
  };
}

/** Metadata-only row — the shape the list endpoint returns (no bytes). */
function makeMeta(tradeKey: string, id = "shot-1") {
  return {
    id,
    trade_key: tradeKey,
    content_type: "image/png",
    size: 128,
    created_at: "2026-04-13T10:00:00",
  };
}

/** Full row (metadata + data_url) — the per-id GET / attach POST shape. */
function makeScreenshot(tradeKey: string, id = "shot-1") {
  return { ...makeMeta(tradeKey, id), data_url: FAKE_DATA_URL };
}

function renderFills(ui: React.ReactElement = <FillsWidget {...makeDockviewPanelProps()} />) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function resetMocks() {
  vi.clearAllMocks();
  localStorageMock.clear();
  runtime.mode = "live";
  mockUseAccountReadsEnabled.mockReturnValue(true);
  mockUseTradebook.mockReturnValue(queryResult({ data: [] }));
  mockJournal.mockResolvedValue({ trades: [], total: 0 });
  mockList.mockResolvedValue([]);
  mockGet.mockImplementation((id: string) =>
    Promise.resolve(makeScreenshot("whatever", id)),
  );
  mockAdd.mockResolvedValue(makeScreenshot("whatever"));
  mockDelete.mockResolvedValue({ deleted: "shot-1" });
}

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  global.URL.createObjectURL = vi.fn(() => "blob:mock");
  global.URL.revokeObjectURL = vi.fn();
});

// ---------------------------------------------------------------------------
// Model: joining, mapping, stats, CSV
// ---------------------------------------------------------------------------

describe("buildFillRows", () => {
  it("joins journal enrichment onto the tradebook row by broker order id", () => {
    const book: RawFillSource[] = [{
      symbol: "BANKNIFTY FUT", action: "SELL", quantity: "15",
      average_price: "48520.00", trade_time: "2026-06-05T10:48:55+05:30", orderid: "OA-2",
    }];
    const rows = buildFillRows(book, [JOURNAL_TRADES[1]]);
    expect(rows).toHaveLength(1);
    // Enrichment comes from the journal…
    expect(rows[0].pnl).toBe(5625);
    expect(rows[0].fees).toBe(12.5);
    expect(rows[0].entryPrice).toBe(48150);
    expect(rows[0].tradeKey).toBe(stableTradeKey(JOURNAL_TRADES[1]));
    // …but the broker book's fill facts win where the stores disagree.
    expect(rows[0].price).toBe(48520);
  });

  it("falls back to an exact symbol|side|qty|price match when order ids are missing", () => {
    const book: RawFillSource[] = [{
      symbol: "BANKNIFTY FUT", action: "SELL", quantity: "15",
      average_price: "48525.00", trade_time: "2026-06-05T10:48:55+05:30",
    }];
    const journal = [{ ...JOURNAL_TRADES[1], orderid: undefined }];
    const rows = buildFillRows(book, journal);
    expect(rows).toHaveLength(1);
    expect(rows[0].pnl).toBe(5625);
  });

  it("keeps unmatched journal rows — recorded fills survive a tradebook outage", () => {
    const rows = buildFillRows([], JOURNAL_TRADES);
    expect(rows).toHaveLength(2);
    expect(rows.map((r) => r.symbol)).toEqual(["BANKNIFTY FUT", "BANKNIFTY FUT"]);
  });

  it("excludes unmatched dispatch-time rows that carry no fill evidence", () => {
    // Backend auto-journal rows are written at broker dispatch with NULL
    // pnl/entry/exit (the API returns null despite the declared number type),
    // so a resting, cancelled or rejected order must never surface as a fill.
    const dispatchRow = {
      ...JOURNAL_TRADES[0],
      pnl: null as unknown as number,
      entry_price: 0,
      exit_price: 0,
    };
    const rows = buildFillRows([], [dispatchRow, JOURNAL_TRADES[1]]);
    expect(rows).toHaveLength(1);
    expect(rows[0].pnl).toBe(5625);
  });

  it("keeps unmatched tradebook rows with null enrichment", () => {
    const rows = buildFillRows(BOOK_TRADES, []);
    expect(rows).toHaveLength(3);
    for (const r of rows) {
      expect(r.pnl).toBeNull();
      expect(r.fees).toBeNull();
      expect(r.entryPrice).toBeNull();
      expect(r.exitPrice).toBeNull();
      expect(r.tradeKey).toBeNull();
    }
  });

  it("sorts the union newest first", () => {
    const rows = buildFillRows(BOOK_TRADES, JOURNAL_TRADES);
    const times = rows.map((r) => r.timeSortMs);
    expect([...times].sort((a, b) => b - a)).toEqual(times);
    // Journal rows (June) are newer than the book rows (April) here.
    expect(rows[0].symbol).toBe("BANKNIFTY FUT");
  });
});

describe("journalToFills", () => {
  it("maps side, qty, price and strategy from the journal row", () => {
    const [buy, sell] = journalToFills(JOURNAL_TRADES);
    expect(buy.side).toBe("BUY");
    expect(buy.qty).toBe(15);
    expect(sell.side).toBe("SELL");
    expect(sell.price).toBe(48525);
    expect(sell.strategy).toBe("manual");
  });

  it("uses the broker orderid as the row id", () => {
    expect(journalToFills(JOURNAL_TRADES)[0].id).toBe("OA-1");
  });

  it("coerces a missing/non-numeric pnl to null", () => {
    const row = { ...JOURNAL_TRADES[0], pnl: undefined as unknown as number };
    expect(journalToFills([row])[0].pnl).toBeNull();
  });

  it("never fabricates enrichment on opening legs — zeros mean 'not recorded'", () => {
    const [openingLeg] = journalToFills(JOURNAL_TRADES);
    expect(openingLeg.entryPrice).toBeNull();
    expect(openingLeg.exitPrice).toBeNull();
    expect(openingLeg.fees).toBeNull();
  });

  it("leaves an empty strategy null rather than inventing 'manual'", () => {
    const row = { ...JOURNAL_TRADES[0], strategy: "" };
    expect(journalToFills([row])[0].strategy).toBeNull();
  });

  it("computes the stable screenshot key exactly as the Trade Journal tool does", () => {
    const [row] = journalToFills([JOURNAL_TRADES[0]]);
    expect(row.tradeKey).toBe("2026-06-05T10:02:08+05:30|BANKNIFTY FUT|OA-1");
    const noOrderId = journalToFills([{ ...JOURNAL_TRADES[0], orderid: undefined }]);
    expect(noOrderId[0].tradeKey).toBe("2026-06-05T10:02:08+05:30|BANKNIFTY FUT|na");
  });
});

describe("computeFillStats", () => {
  it("returns zero stats for an empty array", () => {
    const stats = computeFillStats([]);
    expect(stats.fills).toBe(0);
    expect(stats.realisedPnl).toBe(0);
    expect(stats.totalFees).toBeNull();
  });

  it("sums realised P&L directly — never halves (the TradeLog /2 path is gone)", () => {
    const rows = journalToFills(JOURNAL_TRADES);
    // Opening leg carries 0, closing leg carries the round trip: direct sum.
    expect(computeFillStats(rows).realisedPnl).toBe(5625);
    // Two closing legs of 100 each are 200 — a paired-halving would say 100.
    const twoLegs = journalToFills([
      { ...JOURNAL_TRADES[1], pnl: 100 },
      { ...JOURNAL_TRADES[1], pnl: 100 },
    ]);
    expect(computeFillStats(twoLegs).realisedPnl).toBe(200);
  });

  it("sums fees where present and reports null when no row carried fee data", () => {
    const rows = journalToFills(JOURNAL_TRADES);
    expect(computeFillStats(rows).totalFees).toBe(12.5);
    const noFees = journalToFills([JOURNAL_TRADES[0]]);
    expect(computeFillStats(noFees).totalFees).toBeNull();
  });
});

describe("fillsToCsv", () => {
  it("exports the union of all three ancestors' columns", () => {
    const csv = fillsToCsv(journalToFills(JOURNAL_TRADES));
    expect(csv.split("\n")[0]).toBe(
      "Date,Time,Symbol,Exchange,Side,Qty,Price,Value,Entry,Exit,P&L,Fees,Strategy",
    );
    expect(csv).toContain("BANKNIFTY FUT");
    expect(csv).toContain("5625");
  });

  it("quotes fields containing commas or quotes (the TradeLog export did not)", () => {
    const rows = journalToFills([
      { ...JOURNAL_TRADES[1], strategy: 'Mean, "Rev"' },
    ]);
    const csv = fillsToCsv(rows);
    expect(csv).toContain('"Mean, ""Rev"""');
    // The quoted field must not add columns.
    const header = csv.split("\n")[0].split(",").length;
    expect(csv.split("\n")[1].match(/,(?=(?:[^"]*"[^"]*")*[^"]*$)/g)?.length).toBe(header - 1);
  });
});

describe("SAMPLE_FILLS", () => {
  it("has at least 5 entries with unique ids", () => {
    expect(SAMPLE_FILLS.length).toBeGreaterThanOrEqual(5);
    const ids = SAMPLE_FILLS.map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("contains only executed fills with positive qty and price", () => {
    for (const e of SAMPLE_FILLS) {
      expect(e.qty).toBeGreaterThan(0);
      expect(e.price).toBeGreaterThan(0);
      expect(["BUY", "SELL"]).toContain(e.side);
    }
  });

  it("records P&L on closing legs only, per the backend auto-journal convention", () => {
    for (const e of SAMPLE_FILLS) {
      if (e.pnl !== null) {
        expect(e.entryPrice).not.toBeNull();
        expect(e.exitPrice).not.toBeNull();
        expect(e.side).toBe("SELL");
      }
    }
  });

  it("totals by direct sum — no halving", () => {
    expect(computeFillStats([...SAMPLE_FILLS]).realisedPnl).toBe(10685);
  });
});

// ---------------------------------------------------------------------------
// Widget: Explore mode
// ---------------------------------------------------------------------------

describe("FillsWidget (explore)", () => {
  beforeEach(() => {
    resetMocks();
    runtime.mode = "explore";
    mockUseAccountReadsEnabled.mockReturnValue(false);
  });

  it("shows clearly badged sample fills", () => {
    renderFills();
    expect(screen.getByText("Sample data")).toBeInTheDocument();
    // Both legs of the sample round trip render.
    expect(screen.getAllByText("NIFTY 22200 CE")).toHaveLength(2);
  });

  it("fires no queries — sample mode is fully offline", () => {
    renderFills();
    expect(mockUseTradebook).toHaveBeenCalledWith({ enabled: false });
    expect(mockJournal).not.toHaveBeenCalled();
    expect(mockList).not.toHaveBeenCalled();
  });

  it("disables attaching against sample fills", () => {
    renderFills();
    const attachBtns = screen.getAllByRole("button", { name: /attach screenshot/i });
    expect(attachBtns.length).toBeGreaterThan(0);
    for (const btn of attachBtns) expect(btn).toBeDisabled();
  });
});

// ---------------------------------------------------------------------------
// Widget: connected / live behaviour
// ---------------------------------------------------------------------------

describe("FillsWidget (live)", () => {
  beforeEach(resetMocks);

  it("renders without crashing", () => {
    const { container } = renderFills();
    expect(container).toBeTruthy();
  });

  it("does not show the Sample badge when live", () => {
    renderFills();
    expect(screen.queryByText("Sample data")).toBeNull();
  });

  it("shows an honest empty state when both sources are empty", async () => {
    renderFills();
    expect(await screen.findByText("No fills today")).toBeInTheDocument();
  });

  it("displays tradebook rows with symbol and side badges", async () => {
    mockUseTradebook.mockReturnValue(queryResult({ data: BOOK_TRADES }));
    renderFills();
    expect(await screen.findByText("NIFTY24APR23000CE")).toBeInTheDocument();
    expect(screen.getByText("NIFTY24APR23000PE")).toBeInTheDocument();
    expect(screen.getByText("BANKNIFTY24APR50000CE")).toBeInTheDocument();
    expect(screen.getAllByText("BUY")).toHaveLength(2);
    expect(screen.getAllByText("SELL")).toHaveLength(1);
  });

  it("shows the total fill count in the header", async () => {
    mockUseTradebook.mockReturnValue(queryResult({ data: BOOK_TRADES }));
    renderFills();
    expect(await screen.findByText("(3)")).toBeInTheDocument();
  });

  it("filters fills by the BUY/SELL pills", async () => {
    mockUseTradebook.mockReturnValue(queryResult({ data: BOOK_TRADES }));
    renderFills();
    await screen.findByText("NIFTY24APR23000CE");
    fireEvent.click(screen.getByText(/^Sell/));
    expect(screen.getByText("NIFTY24APR23000PE")).toBeInTheDocument();
    expect(screen.queryByText("NIFTY24APR23000CE")).not.toBeInTheDocument();
    expect(screen.queryByText("BANKNIFTY24APR50000CE")).not.toBeInTheDocument();
  });

  it("filters fills by symbol search", async () => {
    mockUseTradebook.mockReturnValue(queryResult({ data: BOOK_TRADES }));
    renderFills();
    await screen.findByText("NIFTY24APR23000CE");
    fireEvent.change(screen.getByLabelText("Search symbol"), { target: { value: "BANKNIFTY" } });
    expect(screen.getByText("BANKNIFTY24APR50000CE")).toBeInTheDocument();
    expect(screen.queryByText("NIFTY24APR23000CE")).not.toBeInTheDocument();
    expect(screen.getByText("1 fills")).toBeInTheDocument();
  });

  it("shows a filtered-empty message distinct from the no-data one", async () => {
    mockUseTradebook.mockReturnValue(queryResult({ data: BOOK_TRADES }));
    renderFills();
    await screen.findByText("NIFTY24APR23000CE");
    fireEvent.change(screen.getByLabelText("Search symbol"), { target: { value: "ZZZ" } });
    expect(screen.getByText("No fills match the current filters")).toBeInTheDocument();
    expect(screen.queryByText("No fills today")).not.toBeInTheDocument();
  });

  it("renders the union column headers", async () => {
    mockUseTradebook.mockReturnValue(queryResult({ data: BOOK_TRADES }));
    renderFills();
    await screen.findByText("NIFTY24APR23000CE");
    const headers = screen.getAllByRole("columnheader").map((el) => el.textContent?.trim());
    for (const h of ["Time", "Symbol", "Exch", "Side", "Qty", "Price", "Value", "Entry", "Exit", "P&L", "Fees", "Strategy", "Shot"]) {
      expect(headers).toContain(h);
    }
  });

  it("shows journal-backed realised P&L and fees in the stats footer (direct sum)", async () => {
    mockJournal.mockResolvedValue({ trades: JOURNAL_TRADES, total: 2 });
    renderFills();
    await screen.findAllByText("BANKNIFTY FUT");
    const footer = screen.getByLabelText("Fills statistics");
    expect(within(footer).getByText("+₹5,625")).toBeInTheDocument();
    expect(within(footer).getByText("₹12.5")).toBeInTheDocument();
    expect(within(footer).getByText("2")).toBeInTheDocument();
  });

  it("renders real journal rows, never sample trades, when live", async () => {
    mockJournal.mockResolvedValue({ trades: JOURNAL_TRADES, total: 2 });
    renderFills();
    expect(await screen.findAllByText("BANKNIFTY FUT")).toBeTruthy();
    expect(screen.queryByText("NIFTY 22200 CE")).toBeNull();
  });

  it("exports the filtered rows as CSV", async () => {
    // jsdom cannot navigate to blob: URLs — stub the anchor click.
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    mockUseTradebook.mockReturnValue(queryResult({ data: BOOK_TRADES }));
    renderFills();
    await screen.findByText("NIFTY24APR23000CE");
    fireEvent.click(screen.getByLabelText("Export CSV"));
    expect(global.URL.createObjectURL).toHaveBeenCalled();
    expect(anchorClick).toHaveBeenCalled();
    anchorClick.mockRestore();
  });

  it("shows an error banner with Retry instead of 'No fills today' when the tradebook fetch fails", async () => {
    mockUseTradebook.mockReturnValue(
      queryResult({ data: undefined, isError: true, error: new Error("OpenAlgo server error") }),
    );
    renderFills();
    expect(await screen.findByText(/Failed to load fills: OpenAlgo server error/)).toBeInTheDocument();
    // The journal query resolves async; the empty-state region follows it.
    expect(await screen.findByText("Fills unavailable — retry above")).toBeInTheDocument();
    expect(screen.queryByText("No fills today")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Retry"));
    expect(mockRefetch).toHaveBeenCalled();
  });

  it("keeps rendering fills when only the journal fetch fails (non-blocking notice)", async () => {
    mockUseTradebook.mockReturnValue(queryResult({ data: BOOK_TRADES }));
    mockJournal.mockRejectedValue(new Error("backend down"));
    renderFills();
    expect(await screen.findByText(/Journal details unavailable/)).toBeInTheDocument();
    expect(screen.getByText("NIFTY24APR23000CE")).toBeInTheDocument();
    expect(screen.queryByText(/Failed to load fills/)).not.toBeInTheDocument();
  });

  it("shows skeleton rows while the first fetch is in flight", () => {
    mockUseTradebook.mockReturnValue(queryResult({ isLoading: true, isPending: true, isFetching: true }));
    renderFills();
    expect(screen.getByLabelText("Loading fills")).toBeInTheDocument();
  });

  it("queries the journal when live", async () => {
    renderFills();
    await waitFor(() => expect(mockJournal).toHaveBeenCalled());
  });

  it("does not query the journal or screenshots in Practice — sandbox fills only", async () => {
    runtime.mode = "practice";
    mockUseTradebook.mockReturnValue(queryResult({ data: BOOK_TRADES }));
    renderFills();
    expect(await screen.findByText("NIFTY24APR23000CE")).toBeInTheDocument();
    expect(mockJournal).not.toHaveBeenCalled();
    expect(mockList).not.toHaveBeenCalled();
  });

  it("shows 'Broker required' but still renders recorded journal fills without a broker", async () => {
    mockUseAccountReadsEnabled.mockReturnValue(false);
    mockJournal.mockResolvedValue({ trades: JOURNAL_TRADES, total: 2 });
    renderFills();
    expect(mockUseTradebook).toHaveBeenCalledWith({ enabled: false });
    expect(screen.getByText("Broker required")).toBeInTheDocument();
    // The retired TradeLog hid these real local rows behind sample data.
    expect(await screen.findAllByText("BANKNIFTY FUT")).toBeTruthy();
    expect(screen.queryByText("Sample data")).toBeNull();
  });

  it("prompts to connect a broker when nothing at all is available", async () => {
    mockUseAccountReadsEnabled.mockReturnValue(false);
    renderFills();
    expect(await screen.findByText("Connect a broker to load fills")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Embeddable surface (Trade Review Log tab)
// ---------------------------------------------------------------------------

describe("FillsTable (embedded, date-ranged)", () => {
  beforeEach(resetMocks);

  it("queries the journal for the range and skips the session tradebook join", async () => {
    renderFills(<FillsTable startDate="2026-06-01" endDate="2026-06-07" />);
    await waitFor(() =>
      expect(mockJournal).toHaveBeenCalledWith("2026-06-01", "2026-06-07", undefined, 200),
    );
    expect(mockUseTradebook).toHaveBeenCalledWith({ enabled: false });
  });

  it("shows a period-scoped empty message", async () => {
    renderFills(<FillsTable startDate="2026-06-01" endDate="2026-06-07" />);
    expect(await screen.findByText("No fills in this period")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Screenshots (ported from the TradeLogTab suite)
// ---------------------------------------------------------------------------

describe("Fills screenshots", () => {
  beforeEach(resetMocks);

  it("shows the Shot column header", async () => {
    mockJournal.mockResolvedValue({ trades: [makeTrade()], total: 1 });
    renderFills();
    expect(await screen.findByText("Shot")).toBeInTheDocument();
  });

  it("renders a screenshot attach button for each journal-backed fill", async () => {
    mockJournal.mockResolvedValue({
      trades: [makeTrade({ symbol: "TCS" }), makeTrade({ symbol: "WIPRO" })],
      total: 2,
    });
    renderFills();
    await screen.findByText("TCS");
    // Only buttons (not the hidden file inputs which share the aria-label).
    const attachBtns = screen.getAllByRole("button", { name: /attach screenshot/i });
    expect(attachBtns.length).toBe(2);
    for (const btn of attachBtns) expect(btn).toBeEnabled();
  });

  it("disables attach on tradebook-only fills that have no journal record", async () => {
    mockUseTradebook.mockReturnValue(queryResult({ data: [BOOK_TRADES[0]] }));
    renderFills();
    await screen.findByText("NIFTY24APR23000CE");
    const attachBtn = screen.getByRole("button", { name: /attach screenshot/i });
    expect(attachBtn).toBeDisabled();
  });

  it("renders a thumbnail for a screenshot keyed by the stable trade key", async () => {
    const trade = makeTrade();
    mockJournal.mockResolvedValue({ trades: [trade], total: 1 });
    mockList.mockResolvedValue([makeMeta(stableTradeKey(trade))]);
    renderFills();
    await waitFor(() => {
      expect(
        document.querySelector("img[alt='Trade screenshot thumbnail']"),
      ).toBeInTheDocument();
    });
  });

  it("still renders screenshots stored under the legacy timestamp-symbol-idx key", async () => {
    const trade = makeTrade();
    mockJournal.mockResolvedValue({ trades: [trade], total: 1 });
    mockList.mockResolvedValue([makeMeta(`${trade.timestamp}-${trade.symbol}-0`)]);
    renderFills();
    await waitFor(() => {
      expect(
        document.querySelector("img[alt='Trade screenshot thumbnail']"),
      ).toBeInTheDocument();
    });
  });

  it("attaches a file through the backend mutation with the stable key", async () => {
    const trade = makeTrade();
    mockJournal.mockResolvedValue({ trades: [trade], total: 1 });
    renderFills();
    await screen.findByText("NIFTY");

    const fileInput = document.querySelector("input[type='file']") as HTMLInputElement;
    expect(fileInput).toBeInTheDocument();
    const file = new File(["chart-bytes"], "chart.png", { type: "image/png" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(mockAdd).toHaveBeenCalledWith(
        stableTradeKey(trade),
        expect.stringMatching(/^data:image\/png;base64,/) as unknown,
      );
    });
  });

  it("shows the fill symbol in the viewer dialog title (not a date fragment)", async () => {
    const trade = makeTrade({ symbol: "BANKNIFTY" });
    mockJournal.mockResolvedValue({ trades: [trade], total: 1 });
    mockList.mockResolvedValue([makeMeta(stableTradeKey(trade))]);
    renderFills();

    const thumb = await screen.findByRole("button", { name: /view screenshot/i });
    fireEvent.click(thumb);

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("BANKNIFTY")).toBeInTheDocument();
    expect(within(dialog).queryByText("04")).not.toBeInTheDocument();
  });

  it("removes a screenshot through the delete mutation", async () => {
    const trade = makeTrade();
    mockJournal.mockResolvedValue({ trades: [trade], total: 1 });
    mockList.mockResolvedValue([makeMeta(stableTradeKey(trade), "shot-9")]);
    renderFills();

    const thumb = await screen.findByRole("button", { name: /view screenshot/i });
    fireEvent.click(thumb);
    fireEvent.click(screen.getByRole("button", { name: /remove screenshot/i }));

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith("shot-9"));
  });
});

// ---------------------------------------------------------------------------
// Lazy per-thumbnail byte fetching (ported from the TradeLogTab suite)
// ---------------------------------------------------------------------------

describe("Fills lazy screenshot bytes", () => {
  beforeEach(resetMocks);

  it("fetches each thumbnail's bytes per-id — the list carries metadata only", async () => {
    const trade = makeTrade();
    mockJournal.mockResolvedValue({ trades: [trade], total: 1 });
    mockList.mockResolvedValue([makeMeta(stableTradeKey(trade), "shot-7")]);
    renderFills();

    const img = await waitFor(() => {
      const el = document.querySelector("img[alt='Trade screenshot thumbnail']");
      expect(el).toBeInTheDocument();
      return el as HTMLImageElement;
    });
    expect(mockGet).toHaveBeenCalledWith("shot-7");
    expect(img).toHaveAttribute("src", FAKE_DATA_URL);
  });

  it("shows a loading placeholder while a thumbnail's bytes are in flight", async () => {
    const trade = makeTrade();
    mockJournal.mockResolvedValue({ trades: [trade], total: 1 });
    mockList.mockResolvedValue([makeMeta(stableTradeKey(trade))]);
    mockGet.mockImplementation(() => new Promise(() => undefined)); // never settles
    renderFills();

    expect(await screen.findByLabelText("Loading screenshot")).toBeInTheDocument();
    expect(
      document.querySelector("img[alt='Trade screenshot thumbnail']"),
    ).not.toBeInTheDocument();
  });

  it("shows an honest failure state (with retry) when the byte fetch fails", async () => {
    const trade = makeTrade();
    mockJournal.mockResolvedValue({ trades: [trade], total: 1 });
    mockList.mockResolvedValue([makeMeta(stableTradeKey(trade), "shot-3")]);
    mockGet.mockRejectedValueOnce(new Error("backend unreachable"));
    renderFills();

    const failBtn = await screen.findByRole("button", {
      name: /screenshot failed to load/i,
    });
    expect(
      document.querySelector("img[alt='Trade screenshot thumbnail']"),
    ).not.toBeInTheDocument();

    fireEvent.click(failBtn);
    await waitFor(() => {
      expect(
        document.querySelector("img[alt='Trade screenshot thumbnail']"),
      ).toBeInTheDocument();
    });
  });

  it("attach seeds the new id's data query from the POST response — no byte refetch", async () => {
    const trade = makeTrade();
    const key = stableTradeKey(trade);
    mockJournal.mockResolvedValue({ trades: [trade], total: 1 });
    mockAdd.mockResolvedValue(makeScreenshot(key, "shot-new"));
    // First list: nothing attached; post-attach refetch: the new metadata row.
    mockList.mockResolvedValue([makeMeta(key, "shot-new")]);
    mockList.mockResolvedValueOnce([]);
    renderFills();
    await screen.findByText("NIFTY");

    const fileInput = document.querySelector("input[type='file']") as HTMLInputElement;
    const file = new File(["chart-bytes"], "chart.png", { type: "image/png" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => expect(mockAdd).toHaveBeenCalled());
    const img = await waitFor(() => {
      const el = document.querySelector("img[alt='Trade screenshot thumbnail']");
      expect(el).toBeInTheDocument();
      return el as HTMLImageElement;
    });
    expect(img).toHaveAttribute("src", FAKE_DATA_URL);
    expect(mockGet).not.toHaveBeenCalled();
  });

  it("delete invalidates only the metadata list — surviving thumbnails keep their bytes", async () => {
    const tradeA = makeTrade({ symbol: "AAA", timestamp: "2026-04-13T09:30:00" });
    const tradeB = makeTrade({ symbol: "BBB", timestamp: "2026-04-13T10:30:00" });
    mockJournal.mockResolvedValue({ trades: [tradeA, tradeB], total: 2 });
    mockList.mockResolvedValue([
      makeMeta(stableTradeKey(tradeA), "shot-a"),
      makeMeta(stableTradeKey(tradeB), "shot-b"),
    ]);
    renderFills();

    await waitFor(() => {
      expect(
        document.querySelectorAll("img[alt='Trade screenshot thumbnail']").length,
      ).toBe(2);
    });
    expect(mockGet).toHaveBeenCalledTimes(2);

    const rowA = screen.getByText("AAA").closest("tr") as HTMLTableRowElement;
    fireEvent.click(within(rowA).getByRole("button", { name: /view screenshot/i }));
    mockList.mockResolvedValue([makeMeta(stableTradeKey(tradeB), "shot-b")]);
    fireEvent.click(screen.getByRole("button", { name: /remove screenshot/i }));

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith("shot-a"));
    await waitFor(() => {
      expect(
        document.querySelectorAll("img[alt='Trade screenshot thumbnail']").length,
      ).toBe(1);
    });
    expect(mockGet).toHaveBeenCalledTimes(2);
  });
});

// ---------------------------------------------------------------------------
// One-time legacy localStorage import (ported from the TradeLogTab suite)
// ---------------------------------------------------------------------------

describe("Fills legacy screenshot import", () => {
  beforeEach(resetMocks);

  it("POSTs each legacy entry verbatim and removes the key after all succeed", async () => {
    localStorageMock.setItem(
      SCREENSHOTS_KEY,
      JSON.stringify({
        "2026-04-13T09:30:00-NIFTY-0": FAKE_DATA_URL,
        "2026-04-13T10:30:00-INFY-1": FAKE_DATA_URL,
      }),
    );
    renderFills();

    await waitFor(() => expect(mockAdd).toHaveBeenCalledTimes(2));
    expect(mockAdd).toHaveBeenCalledWith("2026-04-13T09:30:00-NIFTY-0", FAKE_DATA_URL);
    expect(mockAdd).toHaveBeenCalledWith("2026-04-13T10:30:00-INFY-1", FAKE_DATA_URL);
    await waitFor(() =>
      expect(localStorageMock.getItem(SCREENSHOTS_KEY)).toBeNull(),
    );
  });

  it("rewrites the map to only the failed entries so successes are never re-uploaded", async () => {
    localStorageMock.setItem(
      SCREENSHOTS_KEY,
      JSON.stringify({ good: FAKE_DATA_URL, bad: FAKE_DATA_URL }),
    );
    mockAdd.mockImplementation((tradeKey: string) =>
      tradeKey === "bad"
        ? Promise.reject(new Error("backend down"))
        : Promise.resolve(makeScreenshot(tradeKey)),
    );
    renderFills();

    await waitFor(() => expect(mockAdd).toHaveBeenCalledTimes(2));
    await waitFor(() => {
      const raw = localStorageMock.getItem(SCREENSHOTS_KEY);
      expect(raw).not.toBeNull();
      expect(JSON.parse(raw as string)).toEqual({ bad: FAKE_DATA_URL });
    });
  });

  it("surfaces permanently rejected entries with a one-line notice", async () => {
    localStorageMock.setItem(
      SCREENSHOTS_KEY,
      JSON.stringify({ ok: FAKE_DATA_URL, "bmp-shot": FAKE_DATA_URL }),
    );
    mockAdd.mockImplementation((tradeKey: string) =>
      tradeKey === "bmp-shot"
        ? Promise.reject(
            Object.assign(new Error("Unsupported screenshot type"), { status: 400 }),
          )
        : Promise.resolve(makeScreenshot(tradeKey)),
    );
    renderFills();

    expect(
      await screen.findByText(/1 legacy screenshot could not be migrated/),
    ).toBeInTheDocument();
    await waitFor(() => {
      const raw = localStorageMock.getItem(SCREENSHOTS_KEY);
      expect(raw).not.toBeNull();
      expect(JSON.parse(raw as string)).toEqual({ "bmp-shot": FAKE_DATA_URL });
    });
  });

  it("shows no rejection notice for transient failures", async () => {
    localStorageMock.setItem(SCREENSHOTS_KEY, JSON.stringify({ flaky: FAKE_DATA_URL }));
    mockAdd.mockRejectedValue(new Error("network down"));
    renderFills();

    await waitFor(() => expect(mockAdd).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByText(/could not be migrated/)).not.toBeInTheDocument();
    expect(localStorageMock.getItem(SCREENSHOTS_KEY)).not.toBeNull();
  });

  it("skips the import entirely in Explore mode", async () => {
    runtime.mode = "explore";
    mockUseAccountReadsEnabled.mockReturnValue(false);
    localStorageMock.setItem(SCREENSHOTS_KEY, JSON.stringify({ "old-key": FAKE_DATA_URL }));
    renderFills();

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(mockAdd).not.toHaveBeenCalled();
    expect(localStorageMock.getItem(SCREENSHOTS_KEY)).not.toBeNull();
  });
});
