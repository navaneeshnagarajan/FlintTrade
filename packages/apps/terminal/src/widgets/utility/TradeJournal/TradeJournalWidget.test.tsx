import { describe, it, expect, vi, beforeEach } from "vitest";
import type { ReactNode } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mock the journal API client
// ---------------------------------------------------------------------------
vi.mock("@/services/ftApi.journal", () => ({
  listJournalEntries: vi.fn(),
  searchJournalEntries: vi.fn(),
  createJournalEntry: vi.fn(),
  updateJournalEntry: vi.fn(),
  deleteJournalEntry: vi.fn(),
  getJournalStats: vi.fn(),
  fetchJournalCsv: vi.fn(),
}));

// Mock the Radix Dialog to avoid portal/focus-trap complexity in JSDOM. The
// content only renders when `open` is true — mirroring real dialog behaviour.
vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({ open, children }: { open?: boolean; children: ReactNode }) =>
    open ? <div>{children}</div> : null,
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogDescription: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

// Mock Radix Select — render options inline so state-driven defaults are enough.
vi.mock("@/components/ui/select", () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: ReactNode }) => <button type="button">{children}</button>,
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children, value }: { children: ReactNode; value: string }) => (
    <div data-value={value}>{children}</div>
  ),
  SelectValue: ({ placeholder }: { placeholder?: string }) => <span>{placeholder}</span>,
}));

// Mock AlertDialog — only render when open, same as the real confirm dialog.
vi.mock("@/components/ui/alert-dialog", () => ({
  AlertDialog: ({ open, children }: { open?: boolean; children: ReactNode }) =>
    open ? <div>{children}</div> : null,
  AlertDialogAction: ({ children, onClick }: { children: ReactNode; onClick?: () => void }) => (
    <button type="button" onClick={onClick}>{children}</button>
  ),
  AlertDialogCancel: ({ children }: { children: ReactNode }) => <button type="button">{children}</button>,
  AlertDialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  AlertDialogDescription: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  AlertDialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  AlertDialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  AlertDialogTitle: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

import {
  listJournalEntries,
  searchJournalEntries,
  createJournalEntry,
  getJournalStats,
} from "@/services/ftApi.journal";
import type { JournalEntry, JournalStats } from "@/services/ftApi.journal";
import TradeJournalWidget from "./TradeJournalWidget";

const mockList = listJournalEntries as unknown as ReturnType<typeof vi.fn>;
const mockSearch = searchJournalEntries as unknown as ReturnType<typeof vi.fn>;
const mockCreate = createJournalEntry as unknown as ReturnType<typeof vi.fn>;
const mockStats = getJournalStats as unknown as ReturnType<typeof vi.fn>;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------
function makeEntry(overrides: Partial<JournalEntry> = {}): JournalEntry {
  return {
    id: "e1",
    symbol: "NIFTY",
    exchange: "NFO",
    side: "BUY",
    quantity: 50,
    entry_price: 100,
    exit_price: 125,
    entry_time: null,
    exit_time: null,
    strategy: "Breakout",
    tags: ["momentum"],
    notes: "Clean breakout above the range.",
    screenshot_path: null,
    emotion_before: null,
    emotion_after: null,
    setup_quality: 4,
    execution_quality: 3,
    pnl: 1250,
    pnl_pct: 25,
    risk_reward_ratio: null,
    created_at: "2026-07-01T05:00:00Z",
    updated_at: "2026-07-01T05:00:00Z",
    ...overrides,
  };
}

const STATS: JournalStats = {
  total_entries: 2,
  closed_entries: 1,
  win_count: 3,
  loss_count: 2,
  win_rate: 60,
  avg_pnl: 1250,
  total_pnl: 1250,
  best_trade_pnl: 1250,
  worst_trade_pnl: -400,
  avg_setup_quality: 4,
  avg_execution_quality: 3,
  by_strategy: { Breakout: 1 },
  by_day_of_week: { Mon: 1 },
};

function renderWidget() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <TradeJournalWidget />
    </QueryClientProvider>,
  );
}

describe("TradeJournalWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockList.mockResolvedValue({
      entries: [makeEntry(), makeEntry({ id: "e2", symbol: "BANKNIFTY", side: "SELL", pnl: -400 })],
      total: 2,
    });
    mockSearch.mockResolvedValue({ entries: [makeEntry()], total: 1 });
    mockStats.mockResolvedValue(STATS);
    mockCreate.mockResolvedValue(makeEntry({ id: "new" }));
  });

  it("renders the entry list from the entries endpoint", async () => {
    renderWidget();
    expect(await screen.findByText("NIFTY")).toBeInTheDocument();
    expect(screen.getByText("BANKNIFTY")).toBeInTheDocument();
    expect(mockList).toHaveBeenCalledTimes(1);
    expect(mockSearch).not.toHaveBeenCalled();
  });

  it("shows P&L coloured by sign and the win-rate stat", async () => {
    renderWidget();
    // Positive P&L rendered with a signed rupee figure and the profit colour
    // (the row P&L and the stats Total P&L both surface this value).
    const profits = await screen.findAllByText("+₹1,250.00");
    expect(profits.length).toBeGreaterThanOrEqual(1);
    expect(profits.some((el) => el.classList.contains("text-profit"))).toBe(true);
    // Negative P&L renders with the loss colour.
    const loss = screen.getByText("−₹400.00");
    expect(loss).toHaveClass("text-loss");
    // Win-rate stat: backend sends a percentage (60), rendered verbatim — a
    // scaling regression would show 6000.0%.
    expect(await screen.findByText("60.0%")).toBeInTheDocument();
  });

  it("switches to the search endpoint when the search box is used", async () => {
    renderWidget();
    await screen.findByText("NIFTY");

    fireEvent.change(screen.getByLabelText("Search journal"), {
      target: { value: "breakout" },
    });

    await waitFor(() =>
      expect(mockSearch).toHaveBeenCalledWith({ q: "breakout", limit: 200 }),
    );
  });

  it("submits a new entry via createJournalEntry", async () => {
    renderWidget();
    await screen.findByText("NIFTY");

    fireEvent.click(screen.getByRole("button", { name: /add journal entry/i }));

    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "reliance" } });
    fireEvent.change(screen.getByLabelText("Exchange"), { target: { value: "NSE" } });
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("Entry price"), { target: { value: "2500" } });

    fireEvent.click(screen.getByRole("button", { name: "Save entry" }));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(mockCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        symbol: "RELIANCE",
        exchange: "NSE",
        side: "BUY",
        quantity: 10,
        entry_price: 2500,
      }),
    );
  });

  it("renders an honest empty state when there are no entries", async () => {
    mockList.mockResolvedValue({ entries: [], total: 0 });
    renderWidget();
    expect(await screen.findByText("No journal entries yet.")).toBeInTheDocument();
  });

  it("surfaces a load error", async () => {
    mockList.mockRejectedValue(new Error("journal store unavailable"));
    renderWidget();
    expect(await screen.findByText("journal store unavailable")).toBeInTheDocument();
  });
});
