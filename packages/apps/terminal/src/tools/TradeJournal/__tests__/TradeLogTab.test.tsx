/**
 * TradeLogTab.test.tsx
 *
 * Tests for the TradeLogTab component including the screenshot attachment feature.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

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
  Input: ({ ...props }: React.InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
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

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TradeLogTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.clear();
  });

  it("renders without crashing with empty trades", () => {
    render(<TradeLogTab {...defaultProps} />);
    expect(screen.getByText(/no trades found/i)).toBeInTheDocument();
  });

  it("renders trade rows", () => {
    const trades = [makeTrade({ symbol: "INFY" })];
    render(<TradeLogTab {...defaultProps} trades={trades} />);
    expect(screen.getByText("INFY")).toBeInTheDocument();
  });

  it("shows Screenshot column header", () => {
    render(<TradeLogTab {...defaultProps} />);
    expect(screen.getByText("Shot")).toBeInTheDocument();
  });

  it("renders screenshot attach button for each trade", () => {
    const trades = [makeTrade({ symbol: "TCS" }), makeTrade({ symbol: "WIPRO" })];
    render(<TradeLogTab {...defaultProps} trades={trades} />);
    // Only query buttons (not the hidden file input which also has the aria-label)
    const attachBtns = screen.getAllByRole("button", { name: /attach screenshot/i });
    expect(attachBtns.length).toBe(2);
  });

  it("shows loading skeleton rows", () => {
    render(<TradeLogTab {...defaultProps} isLoading={true} />);
    expect(screen.getAllByText("Loading…").length).toBeGreaterThan(0);
  });

  it("shows error state with retry button", () => {
    const onRetry = vi.fn();
    render(<TradeLogTab {...defaultProps} isError={true} onRetry={onRetry} />);
    expect(screen.getByText(/failed to load trade journal/i)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/retry/i));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("filters trades by symbol search", () => {
    const trades = [
      makeTrade({ symbol: "NIFTY" }),
      makeTrade({ symbol: "BANKNIFTY" }),
    ];
    render(<TradeLogTab {...defaultProps} trades={trades} />);

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
    render(<TradeLogTab {...defaultProps} trades={trades} />);

    fireEvent.click(screen.getByRole("button", { name: "SELL" }));
    expect(screen.queryByText("NIFTY")).not.toBeInTheDocument();
    expect(screen.getByText("INFY")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Screenshot localStorage persistence tests
// ---------------------------------------------------------------------------

describe("TradeLogTab screenshot persistence", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.clear();
  });

  it("loads previously stored screenshots from localStorage on mount", () => {
    // tradeKey(trade, 0) = `${trade.timestamp}-${trade.symbol}-0`
    const trade = makeTrade({ symbol: "NIFTY" });
    const key = `${trade.timestamp}-${trade.symbol}-0`;
    const fakeDataUrl = "data:image/png;base64,iVBORw0KGgo=";
    localStorageMock.setItem(
      "flinttrade_journal_screenshots",
      JSON.stringify({ [key]: fakeDataUrl }),
    );

    render(<TradeLogTab {...defaultProps} trades={[trade]} />);

    // When a screenshot exists, we render an img thumbnail — not the camera button
    const thumbnail = document.querySelector("img[alt='Trade screenshot thumbnail']");
    expect(thumbnail).toBeInTheDocument();
  });

  it("opens view dialog when thumbnail is clicked", () => {
    const trade = makeTrade({ symbol: "NIFTY" });
    const key = `${trade.timestamp}-${trade.symbol}-0`;
    const fakeDataUrl = "data:image/png;base64,iVBORw0KGgo=";
    localStorageMock.setItem(
      "flinttrade_journal_screenshots",
      JSON.stringify({ [key]: fakeDataUrl }),
    );

    render(<TradeLogTab {...defaultProps} trades={[trade]} />);

    const thumbnail = document.querySelector("button[title='Click to view screenshot']") as HTMLElement;
    expect(thumbnail).toBeInTheDocument();
    fireEvent.click(thumbnail);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/trade screenshot/i)).toBeInTheDocument();
  });
});
