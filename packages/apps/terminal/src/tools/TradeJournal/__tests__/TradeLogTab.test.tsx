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
const mockAdd = vi.fn();
const mockDelete = vi.fn();
vi.mock("@/services/ftApi.journal", () => ({
  listJournalScreenshots: () => mockList() as Promise<unknown>,
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

function makeScreenshot(tradeKey: string, id = "shot-1") {
  return {
    id,
    trade_key: tradeKey,
    content_type: "image/png",
    size: 128,
    created_at: "2026-04-13T10:00:00",
    data_url: FAKE_DATA_URL,
  };
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
    mockAdd.mockResolvedValue(makeScreenshot("whatever"));
    mockDelete.mockResolvedValue({ deleted: "shot-1" });
  });

  it("renders a thumbnail for a screenshot keyed by the stable trade key", async () => {
    const trade = makeTrade();
    mockList.mockResolvedValue([makeScreenshot(stableKey(trade))]);

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
      makeScreenshot(`${trade.timestamp}-${trade.symbol}-0`),
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
    mockList.mockResolvedValue([makeScreenshot(stableKey(trade))]);

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
    mockList.mockResolvedValue([makeScreenshot(stableKey(trade), "shot-9")]);

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
// One-time legacy localStorage import
// ---------------------------------------------------------------------------

describe("TradeLogTab legacy screenshot import", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.clear();
    runtime.mode = "live";
    mockList.mockResolvedValue([]);
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

  it("keeps the localStorage key when any entry fails to import", async () => {
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
    await waitFor(() =>
      expect(localStorageMock.getItem(SCREENSHOTS_KEY)).not.toBeNull(),
    );
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
