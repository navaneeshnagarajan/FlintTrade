/**
 * TradeLogTab.test.tsx
 *
 * Tests for the TradeLogTab component including the backend-persisted
 * screenshot attachments (real TanStack Query; ftApi.journal mocked) and the
 * one-time legacy localStorage import.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const runtime = { mode: "live" };
vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) =>
    selector({ mode: runtime.mode }),
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

vi.mock("@/lib/formatters", () => ({
  formatCurrencyCompact: (v: number) => `₹${v}`,
  // utils.ts (imported by TradeLogTab) calls formatNumber — must be in the mock
  formatNumber: (v: number, d = 2) => v.toFixed(d),
}));

vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children, ...props }: { children: React.ReactNode; className?: string }) => (
    <span {...props}>{children}</span>
  ),
}));

vi.mock("@/components/ui/input", () => ({
  Input: ({ ...props }: React.ComponentProps<"input">) => <input {...props} />,
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({ children, onClick, disabled, ...rest }: {
    children: React.ReactNode;
    onClick?: () => void;
    disabled?: boolean;
    [key: string]: unknown;
  }) => (
    <button onClick={onClick} disabled={disabled} {...rest}>
      {children}
    </button>
  ),
}));

vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({ children, open }: { children: React.ReactNode; open: boolean }) =>
    open ? <div role="dialog">{children}</div> : null,
  DialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
}));

vi.mock("@/components/ui/table", () => ({
  Table: ({ children }: { children: React.ReactNode }) => <table>{children}</table>,
  TableHeader: ({ children }: { children: React.ReactNode }) => <thead>{children}</thead>,
  TableBody: ({ children }: { children: React.ReactNode }) => <tbody>{children}</tbody>,
  TableHead: ({ children }: { children: React.ReactNode }) => <th>{children}</th>,
  TableRow: ({ children, ...props }: { children: React.ReactNode; [key: string]: unknown }) => (
    <tr {...props}>{children}</tr>
  ),
  TableCell: ({ children, colSpan }: { children: React.ReactNode; colSpan?: number }) => (
    <td colSpan={colSpan}>{children}</td>
  ),
}));

vi.mock("@/components/ui/scroll-area", () => ({
  ScrollArea: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("../SummaryCards", () => ({
  SummaryCards: () => <div data-testid="summary-cards" />,
}));

vi.mock("../StatCard", () => ({
  SkeletonRows: ({ count }: { count: number }) => (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <tr key={i}><td>Loading…</td></tr>
      ))}
    </>
  ),
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
// Import component under test
// ---------------------------------------------------------------------------

import { TradeLogTab } from "../TradeLogTab";
import type { JournalTrade } from "@/services/ftApi";
import type { TradeAnalytics } from "@/lib/journalAnalytics";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SCREENSHOTS_KEY = "flinttrade_journal_screenshots";
const FAKE_DATA_URL = "data:image/png;base64,iVBORw0KGgo=";

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

/** Stable backend trade key for a trade without an orderid. */
function stableKey(trade: JournalTrade): string {
  return `${trade.timestamp}|${trade.symbol}|${trade.orderid ?? "na"}`;
}

/** Metadata-only row — the shape the list endpoint now returns (no bytes). */
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

const emptyAnalytics: TradeAnalytics = {
  totalTrades: 0, netPnl: 0, winRate: 0,
  wins: 0, losses: 0, avgWin: 0, avgLoss: 0,
  profitFactor: 0, bestTrade: 0, worstTrade: 0,
  byDayOfWeek: [], bySymbol: [],
  currentStreak: 0, streakType: "none",
};

const defaultProps = {
  trades: [] as JournalTrade[],
  analytics: emptyAnalytics,
  isLoading: false,
  isError: false,
  onRetry: vi.fn(),
};

function renderTab(props: Partial<typeof defaultProps> = {}) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <TradeLogTab {...defaultProps} {...props} />
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TradeLogTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.clear();
    runtime.mode = "live";
    mockList.mockResolvedValue([]);
    mockGet.mockImplementation((id: string) =>
      Promise.resolve(makeScreenshot("whatever", id)),
    );
    mockAdd.mockResolvedValue(makeScreenshot("whatever"));
    mockDelete.mockResolvedValue({ deleted: "shot-1" });
  });

  it("renders without crashing with empty trades", () => {
    renderTab();
    expect(screen.getByText(/no trades found/i)).toBeInTheDocument();
  });

  it("renders trade rows", () => {
    renderTab({ trades: [makeTrade({ symbol: "INFY" })] });
    expect(screen.getByText("INFY")).toBeInTheDocument();
  });

  it("shows Screenshot column header", () => {
    renderTab();
    expect(screen.getByText("Shot")).toBeInTheDocument();
  });

  it("renders screenshot attach button for each trade", () => {
    renderTab({ trades: [makeTrade({ symbol: "TCS" }), makeTrade({ symbol: "WIPRO" })] });
    // Only query buttons (not the hidden file input which also has the aria-label)
    const attachBtns = screen.getAllByRole("button", { name: /attach screenshot/i });
    expect(attachBtns.length).toBe(2);
  });

  it("shows loading skeleton rows", () => {
    renderTab({ isLoading: true });
    expect(screen.getAllByText("Loading…").length).toBeGreaterThan(0);
  });

  it("shows error state with retry button", () => {
    const onRetry = vi.fn();
    renderTab({ isError: true, onRetry });
    expect(screen.getByText(/failed to load trade journal/i)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/retry/i));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("filters trades by symbol search", () => {
    const trades = [
      makeTrade({ symbol: "NIFTY" }),
      makeTrade({ symbol: "BANKNIFTY" }),
    ];
    renderTab({ trades });

    const searchInput = screen.getByPlaceholderText(/search symbol/i);
    fireEvent.change(searchInput, { target: { value: "BANK" } });

    expect(screen.queryByText("NIFTY")).not.toBeInTheDocument();
    expect(screen.getByText("BANKNIFTY")).toBeInTheDocument();
  });

  it("filters trades by BUY/SELL action", () => {
    const trades = [
      makeTrade({ symbol: "NIFTY", action: "BUY" }),
      makeTrade({ symbol: "INFY", action: "SELL" }),
    ];
    renderTab({ trades });

    fireEvent.click(screen.getByRole("button", { name: "SELL" }));
    expect(screen.queryByText("NIFTY")).not.toBeInTheDocument();
    expect(screen.getByText("INFY")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Backend-persisted screenshot tests
// ---------------------------------------------------------------------------

describe("TradeLogTab screenshots", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.clear();
    runtime.mode = "live";
    mockList.mockResolvedValue([]);
    mockGet.mockImplementation((id: string) =>
      Promise.resolve(makeScreenshot("whatever", id)),
    );
    mockAdd.mockResolvedValue(makeScreenshot("whatever"));
    mockDelete.mockResolvedValue({ deleted: "shot-1" });
  });

  it("renders a thumbnail for a screenshot keyed by the stable trade key", async () => {
    const trade = makeTrade();
    mockList.mockResolvedValue([makeMeta(stableKey(trade))]);

    renderTab({ trades: [trade] });

    await waitFor(() => {
      expect(
        document.querySelector("img[alt='Trade screenshot thumbnail']"),
      ).toBeInTheDocument();
    });
  });

  it("still renders screenshots stored under the legacy timestamp-symbol-idx key", async () => {
    const trade = makeTrade();
    mockList.mockResolvedValue([
      makeMeta(`${trade.timestamp}-${trade.symbol}-0`),
    ]);

    renderTab({ trades: [trade] });

    await waitFor(() => {
      expect(
        document.querySelector("img[alt='Trade screenshot thumbnail']"),
      ).toBeInTheDocument();
    });
  });

  it("attaches a file through the backend mutation with the stable key", async () => {
    const trade = makeTrade();
    renderTab({ trades: [trade] });

    const fileInput = document.querySelector("input[type='file']") as HTMLInputElement;
    expect(fileInput).toBeInTheDocument();
    const file = new File(["chart-bytes"], "chart.png", { type: "image/png" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(mockAdd).toHaveBeenCalledWith(
        stableKey(trade),
        expect.stringMatching(/^data:image\/png;base64,/) as unknown,
      );
    });
  });

  it("shows the trade symbol in the viewer dialog title (not a date fragment)", async () => {
    const trade = makeTrade({ symbol: "BANKNIFTY" });
    mockList.mockResolvedValue([makeMeta(stableKey(trade))]);

    renderTab({ trades: [trade] });

    const thumb = await screen.findByRole("button", { name: /view screenshot/i });
    fireEvent.click(thumb);

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("BANKNIFTY")).toBeInTheDocument();
    // The old code showed `label.split("-")[1]` — a fragment of the timestamp.
    expect(within(dialog).queryByText("04")).not.toBeInTheDocument();
  });

  it("removes a screenshot through the delete mutation", async () => {
    const trade = makeTrade();
    mockList.mockResolvedValue([makeMeta(stableKey(trade), "shot-9")]);

    renderTab({ trades: [trade] });

    const thumb = await screen.findByRole("button", { name: /view screenshot/i });
    fireEvent.click(thumb);
    fireEvent.click(screen.getByRole("button", { name: /remove screenshot/i }));

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith("shot-9"));
  });

  it("disables attaching against sample trades in Explore mode", () => {
    runtime.mode = "explore";
    renderTab({ trades: [makeTrade()] });

    const attachBtn = screen.getByRole("button", { name: /attach screenshot/i });
    expect(attachBtn).toBeDisabled();
    expect(mockList).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Lazy per-thumbnail byte fetching (finding 8, second half)
// ---------------------------------------------------------------------------

describe("TradeLogTab lazy screenshot bytes", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.clear();
    runtime.mode = "live";
    mockList.mockResolvedValue([]);
    mockGet.mockImplementation((id: string) =>
      Promise.resolve(makeScreenshot("whatever", id)),
    );
    mockAdd.mockResolvedValue(makeScreenshot("whatever"));
    mockDelete.mockResolvedValue({ deleted: "shot-1" });
  });

  it("fetches each thumbnail's bytes per-id — the list carries metadata only", async () => {
    const trade = makeTrade();
    mockList.mockResolvedValue([makeMeta(stableKey(trade), "shot-7")]);

    renderTab({ trades: [trade] });

    const img = await waitFor(() => {
      const el = document.querySelector("img[alt='Trade screenshot thumbnail']");
      expect(el).toBeInTheDocument();
      return el as HTMLImageElement;
    });
    // The bytes come from GET /screenshots/<id>, not from the list payload.
    expect(mockGet).toHaveBeenCalledWith("shot-7");
    expect(img).toHaveAttribute("src", FAKE_DATA_URL);
  });

  it("shows a loading placeholder while a thumbnail's bytes are in flight", async () => {
    const trade = makeTrade();
    mockList.mockResolvedValue([makeMeta(stableKey(trade))]);
    mockGet.mockImplementation(() => new Promise(() => undefined)); // never settles

    renderTab({ trades: [trade] });

    expect(await screen.findByLabelText("Loading screenshot")).toBeInTheDocument();
    expect(
      document.querySelector("img[alt='Trade screenshot thumbnail']"),
    ).not.toBeInTheDocument();
  });

  it("shows an honest failure state (with retry) when the byte fetch fails", async () => {
    const trade = makeTrade();
    mockList.mockResolvedValue([makeMeta(stableKey(trade), "shot-3")]);
    mockGet.mockRejectedValueOnce(new Error("backend unreachable"));

    renderTab({ trades: [trade] });

    const failBtn = await screen.findByRole("button", {
      name: /screenshot failed to load/i,
    });
    expect(
      document.querySelector("img[alt='Trade screenshot thumbnail']"),
    ).not.toBeInTheDocument();

    // Clicking retries the per-id fetch and recovers to a real thumbnail.
    fireEvent.click(failBtn);
    await waitFor(() => {
      expect(
        document.querySelector("img[alt='Trade screenshot thumbnail']"),
      ).toBeInTheDocument();
    });
  });

  it("attach seeds the new id's data query from the POST response — no byte refetch", async () => {
    const trade = makeTrade();
    const key = stableKey(trade);
    mockAdd.mockResolvedValue(makeScreenshot(key, "shot-new"));
    // First list: nothing attached; post-attach refetch: the new metadata row.
    mockList.mockResolvedValue([makeMeta(key, "shot-new")]);
    mockList.mockResolvedValueOnce([]);

    renderTab({ trades: [trade] });

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
    // The data_url was already in hand from the POST — a per-id GET here
    // would be the old whole-collection-refetch defect in a new shape.
    expect(mockGet).not.toHaveBeenCalled();
  });

  it("delete invalidates only the metadata list — surviving thumbnails keep their bytes", async () => {
    const tradeA = makeTrade({ symbol: "AAA", timestamp: "2026-04-13T09:30:00" });
    const tradeB = makeTrade({ symbol: "BBB", timestamp: "2026-04-13T10:30:00" });
    mockList.mockResolvedValue([
      makeMeta(stableKey(tradeA), "shot-a"),
      makeMeta(stableKey(tradeB), "shot-b"),
    ]);

    renderTab({ trades: [tradeA, tradeB] });

    await waitFor(() => {
      expect(
        document.querySelectorAll("img[alt='Trade screenshot thumbnail']").length,
      ).toBe(2);
    });
    expect(mockGet).toHaveBeenCalledTimes(2);

    const rowA = screen.getByText("AAA").closest("tr") as HTMLTableRowElement;
    fireEvent.click(within(rowA).getByRole("button", { name: /view screenshot/i }));
    mockList.mockResolvedValue([makeMeta(stableKey(tradeB), "shot-b")]);
    fireEvent.click(screen.getByRole("button", { name: /remove screenshot/i }));

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith("shot-a"));
    await waitFor(() => {
      expect(
        document.querySelectorAll("img[alt='Trade screenshot thumbnail']").length,
      ).toBe(1);
    });
    // The surviving thumbnail's bytes are immutable and cached — the delete
    // must not have triggered any per-id refetch.
    expect(mockGet).toHaveBeenCalledTimes(2);
  });
});

// ---------------------------------------------------------------------------
// One-time legacy localStorage import
// ---------------------------------------------------------------------------

describe("TradeLogTab legacy screenshot import", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.clear();
    runtime.mode = "live";
    mockList.mockResolvedValue([]);
    mockGet.mockImplementation((id: string) =>
      Promise.resolve(makeScreenshot("whatever", id)),
    );
    mockAdd.mockResolvedValue(makeScreenshot("whatever"));
    mockDelete.mockResolvedValue({ deleted: "shot-1" });
  });

  it("POSTs each legacy entry verbatim and removes the key after all succeed", async () => {
    localStorageMock.setItem(
      SCREENSHOTS_KEY,
      JSON.stringify({
        "2026-04-13T09:30:00-NIFTY-0": FAKE_DATA_URL,
        "2026-04-13T10:30:00-INFY-1": FAKE_DATA_URL,
      }),
    );

    renderTab();

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
      JSON.stringify({
        good: FAKE_DATA_URL,
        bad: FAKE_DATA_URL,
      }),
    );
    mockAdd.mockImplementation((tradeKey: string) =>
      tradeKey === "bad"
        ? Promise.reject(new Error("backend down"))
        : Promise.resolve(makeScreenshot(tradeKey)),
    );

    renderTab();

    await waitFor(() => expect(mockAdd).toHaveBeenCalledTimes(2));
    // The key survives (the failed entry must retry on the next mount) but
    // holds ONLY the failure — the succeeded entry's ~MB payload must not be
    // re-POSTed on every future mount.
    await waitFor(() => {
      const raw = localStorageMock.getItem(SCREENSHOTS_KEY);
      expect(raw).not.toBeNull();
      expect(JSON.parse(raw as string)).toEqual({ bad: FAKE_DATA_URL });
    });
  });

  it("surfaces permanently rejected entries with a one-line notice", async () => {
    localStorageMock.setItem(
      SCREENSHOTS_KEY,
      JSON.stringify({
        ok: FAKE_DATA_URL,
        "bmp-shot": FAKE_DATA_URL,
      }),
    );
    mockAdd.mockImplementation((tradeKey: string) =>
      tradeKey === "bmp-shot"
        ? Promise.reject(
            Object.assign(new Error("Unsupported screenshot type"), { status: 400 }),
          )
        : Promise.resolve(makeScreenshot(tradeKey)),
    );

    renderTab();

    // A 4xx is a permanent refusal — the user must be told the screenshot
    // did not migrate instead of it silently vanishing after the upgrade.
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
    localStorageMock.setItem(
      SCREENSHOTS_KEY,
      JSON.stringify({ flaky: FAKE_DATA_URL }),
    );
    mockAdd.mockRejectedValue(new Error("network down"));

    renderTab();

    await waitFor(() => expect(mockAdd).toHaveBeenCalledTimes(1));
    // Transient failures retry silently on the next mount — no scary banner.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByText(/could not be migrated/)).not.toBeInTheDocument();
    expect(localStorageMock.getItem(SCREENSHOTS_KEY)).not.toBeNull();
  });

  it("skips the import entirely in Explore mode", async () => {
    runtime.mode = "explore";
    localStorageMock.setItem(
      SCREENSHOTS_KEY,
      JSON.stringify({ "old-key": FAKE_DATA_URL }),
    );

    renderTab();

    // Allow any (incorrect) import kick-off to surface before asserting.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(mockAdd).not.toHaveBeenCalled();
    expect(localStorageMock.getItem(SCREENSHOTS_KEY)).not.toBeNull();
  });
});
