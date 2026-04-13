/**
 * WatchlistWidget.test.tsx
 *
 * Tests for the multi-tab Watchlist widget.
 * Covers: rendering, default symbols, tab switching, add tab, empty state.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

vi.mock("@/services/api", () => ({
  getMultiQuotes: vi.fn().mockResolvedValue([]),
  searchSymbol:   vi.fn().mockResolvedValue([]),
}));

vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

vi.mock("jotai", () => ({
  useSetAtom: () => vi.fn(),
  atom:       (v: unknown) => v,
}));

vi.mock("@/atoms/marketAtoms", () => ({
  selectedSymbolAtom: {},
}));

// Mock localStorage
const mockLocalStorage: Record<string, string> = {};
vi.stubGlobal("localStorage", {
  getItem:    (key: string) => mockLocalStorage[key] ?? null,
  setItem:    (key: string, val: string) => { mockLocalStorage[key] = val; },
  removeItem: (key: string) => { delete mockLocalStorage[key]; },
  clear:      () => { Object.keys(mockLocalStorage).forEach((k) => delete mockLocalStorage[k]); },
});

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import WatchlistWidget from "../WatchlistWidget";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("WatchlistWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Clear stored watchlists so defaults are used
    delete mockLocalStorage["flinttrade:watchlists"];
    delete mockLocalStorage["flinttrade:watchlist"];
  });

  // --- Existing tests preserved ---

  it("renders without crashing", () => {
    const { container } = render(<WatchlistWidget />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows the Watchlist heading", () => {
    render(<WatchlistWidget />);
    expect(screen.getByText("Watchlist")).toBeInTheDocument();
  });

  it("shows default symbols (NIFTY, BANKNIFTY, SBIN, RELIANCE, HDFCBANK)", () => {
    render(<WatchlistWidget />);
    expect(screen.getByText("NIFTY")).toBeInTheDocument();
    expect(screen.getByText("BANKNIFTY")).toBeInTheDocument();
    expect(screen.getByText("SBIN")).toBeInTheDocument();
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText("HDFCBANK")).toBeInTheDocument();
  });

  it("shows symbol count badge", () => {
    render(<WatchlistWidget />);
    // Default watchlist has 5 symbols
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("has an Add symbol button", () => {
    render(<WatchlistWidget />);
    expect(screen.getByLabelText("Add symbol")).toBeInTheDocument();
  });

  it("shows Add symbol button in empty state", () => {
    mockLocalStorage["flinttrade:watchlists"] = JSON.stringify([
      { id: "t1", name: "Watchlist 1", symbols: [] },
    ]);
    render(<WatchlistWidget />);
    const addButtons = screen.getAllByLabelText("Add symbol");
    expect(addButtons.length).toBeGreaterThanOrEqual(1);
  });

  // --- New multi-tab tests ---

  it("renders the default tab pill labelled 'Watchlist 1'", () => {
    render(<WatchlistWidget />);
    expect(screen.getAllByRole("tab", { name: /watchlist 1/i })[0]).toBeInTheDocument();
  });

  it("shows the 'Add watchlist tab' button", () => {
    render(<WatchlistWidget />);
    expect(screen.getByLabelText("Add watchlist tab")).toBeInTheDocument();
  });

  it("adds a new tab when '+' tab button is clicked", async () => {
    render(<WatchlistWidget />);
    const addTabBtn = screen.getByLabelText("Add watchlist tab");
    await userEvent.click(addTabBtn);
    expect(screen.getAllByRole("tab", { name: /watchlist 2/i })[0]).toBeInTheDocument();
  });

  it("switches active tab when a tab pill is clicked", async () => {
    // Pre-seed two tabs
    mockLocalStorage["flinttrade:watchlists"] = JSON.stringify([
      { id: "t1", name: "Watchlist 1", symbols: [{ symbol: "NIFTY", exchange: "NSE_INDEX" }] },
      { id: "t2", name: "My Options",  symbols: [{ symbol: "BANKNIFTY", exchange: "NSE_INDEX" }] },
    ]);
    render(<WatchlistWidget />);

    // Default tab 1 is active — NIFTY visible
    expect(screen.getByText("NIFTY")).toBeInTheDocument();

    // Switch to tab 2
    const tab2 = screen.getByRole("tab", { name: "My Options" });
    await userEvent.click(tab2);

    // BANKNIFTY should now be visible
    expect(screen.getByText("BANKNIFTY")).toBeInTheDocument();
  });

  it("each tab has its own symbol list that does not leak between tabs", async () => {
    mockLocalStorage["flinttrade:watchlists"] = JSON.stringify([
      { id: "t1", name: "Tab A", symbols: [{ symbol: "SBIN",    exchange: "NSE" }] },
      { id: "t2", name: "Tab B", symbols: [{ symbol: "HDFCBANK", exchange: "NSE" }] },
    ]);
    render(<WatchlistWidget />);

    // Tab A active by default — SBIN visible, HDFCBANK not in symbol list
    expect(screen.getByText("SBIN")).toBeInTheDocument();

    // Switch to Tab B
    await userEvent.click(screen.getByRole("tab", { name: "Tab B" }));
    expect(screen.getByText("HDFCBANK")).toBeInTheDocument();
    // SBIN should not appear as a symbol row after switching
    expect(screen.queryByText("SBIN")).not.toBeInTheDocument();
  });

  it("limits maximum tabs to 5 (add button disappears at limit)", async () => {
    // Pre-seed 5 tabs
    const fiveTabs = Array.from({ length: 5 }, (_, i) => ({
      id:      `t${i + 1}`,
      name:    `Watchlist ${i + 1}`,
      symbols: [],
    }));
    mockLocalStorage["flinttrade:watchlists"] = JSON.stringify(fiveTabs);
    render(<WatchlistWidget />);
    // "Add watchlist tab" button should not be rendered
    expect(screen.queryByLabelText("Add watchlist tab")).not.toBeInTheDocument();
  });

  it("tab context menu appears on right-click of a tab", async () => {
    render(<WatchlistWidget />);
    const tab = screen.getAllByRole("tab", { name: /watchlist 1/i })[0];
    fireEvent.contextMenu(tab);
    expect(screen.getByRole("menuitem", { name: /rename/i })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /duplicate/i })).toBeInTheDocument();
  });

  it("migrates legacy single-list localStorage key", () => {
    const legacy = [
      { symbol: "RELIANCE", exchange: "NSE" },
      { symbol: "TCS",      exchange: "NSE" },
    ];
    mockLocalStorage["flinttrade:watchlist"] = JSON.stringify(legacy);
    render(<WatchlistWidget />);
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText("TCS")).toBeInTheDocument();
  });

  // ── Interaction tests ────────────────────────────────────────────────────

  it("opens the symbol search dialog when Add symbol button is clicked", async () => {
    render(<WatchlistWidget />);
    const addBtn = screen.getByLabelText("Add symbol");
    await userEvent.click(addBtn);
    // SearchDialog renders with role="dialog" and aria-label="Search symbols"
    expect(screen.getByRole("dialog", { name: /search symbols/i })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/search symbol/i)).toBeInTheDocument();
  });

  it("typing in the symbol search input updates the input value", async () => {
    render(<WatchlistWidget />);
    const addBtn = screen.getByLabelText("Add symbol");
    await userEvent.click(addBtn);

    const searchInput = screen.getByPlaceholderText(/search symbol/i) as HTMLInputElement;
    await userEvent.type(searchInput, "INFY");
    expect(searchInput.value).toContain("INFY");
  });

  it("clicking Close search button dismisses the search dialog", async () => {
    render(<WatchlistWidget />);
    await userEvent.click(screen.getByLabelText("Add symbol"));
    expect(screen.getByRole("dialog", { name: /search symbols/i })).toBeInTheDocument();

    // The X button inside the dialog closes it
    const closeBtn = screen.getByLabelText("Close search");
    await userEvent.click(closeBtn);

    expect(screen.queryByRole("dialog", { name: /search symbols/i })).not.toBeInTheDocument();
  });

  it("right-clicking a symbol row opens the context menu with Remove option", async () => {
    mockLocalStorage["flinttrade:watchlists"] = JSON.stringify([
      { id: "t1", name: "Watchlist 1", symbols: [
        { symbol: "NIFTY",    exchange: "NSE_INDEX" },
        { symbol: "RELIANCE", exchange: "NSE" },
      ]},
    ]);
    render(<WatchlistWidget />);

    // Right-click the NIFTY symbol row button
    const niftyRow = screen.getByRole("button", { name: "NIFTY" });
    fireEvent.contextMenu(niftyRow);

    // Symbol context menu should appear with Remove option
    expect(screen.getByRole("menu", { name: /actions for NIFTY/i })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /remove/i })).toBeInTheDocument();
  });
});
