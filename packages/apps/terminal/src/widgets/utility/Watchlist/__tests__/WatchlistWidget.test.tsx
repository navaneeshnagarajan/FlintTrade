/**
 * WatchlistWidget.test.tsx
 *
 * Tests for the multi-tab Watchlist widget.
 * Covers: rendering, default symbols, tab switching, add tab, empty state,
 * and the FDC3 channel bus (row-click broadcasts, joined-to-none silence,
 * quick-trade CreateOrder intent).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

vi.mock("@/services/api", () => ({
  getMultiQuotes: vi.fn().mockResolvedValue([]),
  normaliseMultiQuotes: (raw: { results?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>) => {
    const items = Array.isArray(raw) ? raw : raw.results ?? [];
    return items.map((item) => {
      const data = item.data;
      if (data && typeof data === "object") {
        return { ...(data as Record<string, unknown>), symbol: item.symbol, exchange: item.exchange };
      }
      return item;
    });
  },
  searchSymbol:   vi.fn().mockResolvedValue([]),
}));

vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
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

import { createStore, Provider } from "jotai";
import WatchlistWidget from "../WatchlistWidget";
import { getMultiQuotes } from "@/services/api";
import { selectedSymbolAtom } from "@/atoms/marketAtoms";
import {
  channelInstrumentAtoms,
  DEFAULT_CHANNEL_ID,
  subscribeChannelInstrument,
  USER_CHANNELS,
} from "@/services/fdc3/channels";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";

const mockGetMultiQuotes = vi.mocked(getMultiQuotes);

// ---------------------------------------------------------------------------
// Render helper — real jotai store so channel broadcasts are observable
// ---------------------------------------------------------------------------

function renderWidget(params?: Record<string, unknown>) {
  const store = createStore();
  const props = makeWidgetPanelProps({ params: params ?? {} });
  const view = render(
    <Provider store={store}>
      <WatchlistWidget {...props} />
    </Provider>,
  );
  return { ...view, store, props };
}

/** Capture flinttrade:addWidget event details for the current test. */
function captureAddWidget(): { events: Array<Record<string, unknown>>; stop: () => void } {
  const events: Array<Record<string, unknown>> = [];
  const listener = ((e: Event) => {
    events.push((e as CustomEvent<Record<string, unknown>>).detail);
  }) as EventListener;
  window.addEventListener("flinttrade:addWidget", listener);
  return { events, stop: () => window.removeEventListener("flinttrade:addWidget", listener) };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("WatchlistWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Clear stored watchlists so defaults are used
    delete mockLocalStorage["flinttrade:watchlists"];
    delete mockLocalStorage["flinttrade:watchlist"];
    delete mockLocalStorage["flinttrade:watchlist:view"];
    mockGetMultiQuotes.mockResolvedValue([]);
  });

  // --- Existing tests preserved ---

  it("renders without crashing", () => {
    const { container } = renderWidget();
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows the Watchlist heading", () => {
    renderWidget();
    expect(screen.getByText("Watchlist")).toBeInTheDocument();
  });

  it("shows default symbols (NIFTY, BANKNIFTY, SBIN, RELIANCE, HDFCBANK)", () => {
    renderWidget();
    expect(screen.getByText("NIFTY")).toBeInTheDocument();
    expect(screen.getByText("BANKNIFTY")).toBeInTheDocument();
    expect(screen.getByText("SBIN")).toBeInTheDocument();
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText("HDFCBANK")).toBeInTheDocument();
  });

  it("shows symbol count badge", () => {
    renderWidget();
    // Default watchlist has 5 symbols
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("has an Add symbol button", () => {
    renderWidget();
    expect(screen.getByLabelText("Add symbol")).toBeInTheDocument();
  });

  it("shows Add symbol button in empty state", () => {
    mockLocalStorage["flinttrade:watchlists"] = JSON.stringify([
      { id: "t1", name: "Watchlist 1", symbols: [] },
    ]);
    renderWidget();
    const addButtons = screen.getAllByLabelText("Add symbol");
    expect(addButtons.length).toBeGreaterThanOrEqual(1);
  });

  // --- Multi-tab tests ---

  it("renders the default tab pill labelled 'Watchlist 1'", () => {
    renderWidget();
    expect(screen.getAllByRole("tab", { name: /watchlist 1/i })[0]).toBeInTheDocument();
  });

  it("shows the 'Add watchlist tab' button", () => {
    renderWidget();
    expect(screen.getByLabelText("Add watchlist tab")).toBeInTheDocument();
  });

  it("adds a new tab when '+' tab button is clicked", async () => {
    renderWidget();
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
    renderWidget();

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
    renderWidget();

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
    renderWidget();
    // "Add watchlist tab" button should not be rendered
    expect(screen.queryByLabelText("Add watchlist tab")).not.toBeInTheDocument();
  });

  it("tab context menu appears on right-click of a tab", async () => {
    renderWidget();
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
    renderWidget();
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText("TCS")).toBeInTheDocument();
  });

  // ── Interaction tests ────────────────────────────────────────────────────

  it("opens the symbol search dialog when Add symbol button is clicked", async () => {
    renderWidget();
    const addBtn = screen.getByLabelText("Add symbol");
    await userEvent.click(addBtn);
    // SearchDialog renders with role="dialog" and aria-label="Search symbols"
    expect(screen.getByRole("dialog", { name: /search symbols/i })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/search symbol/i)).toBeInTheDocument();
  });

  it("typing in the symbol search input updates the input value", async () => {
    renderWidget();
    const addBtn = screen.getByLabelText("Add symbol");
    await userEvent.click(addBtn);

    const searchInput = screen.getByPlaceholderText(/search symbol/i) as HTMLInputElement;
    await userEvent.type(searchInput, "INFY");
    expect(searchInput.value).toContain("INFY");
  });

  it("clicking Close search button dismisses the search dialog", async () => {
    renderWidget();
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
    renderWidget();

    // Right-click the NIFTY symbol row button
    const niftyRow = screen.getByRole("button", { name: "NIFTY" });
    fireEvent.contextMenu(niftyRow);

    // Symbol context menu should appear with Remove option
    expect(screen.getByRole("menu", { name: /actions for NIFTY/i })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /remove/i })).toBeInTheDocument();
  });

  it("opens the column manager and persists optional columns", async () => {
    renderWidget();

    await userEvent.click(screen.getByLabelText("More options"));
    await userEvent.click(screen.getByRole("menuitem", { name: /manage columns/i }));

    expect(screen.getByRole("dialog", { name: /watchlist columns/i })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("checkbox", { name: "Volume column" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Formula column" }));

    await waitFor(() => {
      const saved = JSON.parse(mockLocalStorage["flinttrade:watchlist:view"]);
      expect(saved.visibleColumns).toEqual(expect.arrayContaining(["symbol", "volume", "formula"]));
    });
  });

  it("formula selector enables the formula column", async () => {
    renderWidget();

    await userEvent.click(screen.getByLabelText("More options"));
    await userEvent.click(screen.getByRole("menuitem", { name: /manage columns/i }));
    fireEvent.change(screen.getByRole("combobox", { name: "Formula column" }), {
      target: { value: "openGapPct" },
    });

    await waitFor(() => {
      const saved = JSON.parse(mockLocalStorage["flinttrade:watchlist:view"]);
      expect(saved.formula).toBe("openGapPct");
      expect(saved.visibleColumns).toEqual(expect.arrayContaining(["symbol", "formula"]));
    });
  });

  it("renders persisted computed formula and volume columns from live quote data", async () => {
    mockLocalStorage["flinttrade:watchlists"] = JSON.stringify([
      { id: "t1", name: "Watchlist 1", symbols: [{ symbol: "SBIN", exchange: "NSE" }] },
    ]);
    mockLocalStorage["flinttrade:watchlist:view"] = JSON.stringify({
      visibleColumns: ["symbol", "price", "volume", "formula"],
      formula: "rangePct",
    });
    mockGetMultiQuotes.mockResolvedValue([
      {
        symbol: "SBIN",
        exchange: "NSE",
        data: {
          symbol: "SBIN",
          exchange: "NSE",
          ltp: 100,
          open: 98,
          high: 110,
          low: 90,
          close: 99,
          prev_close: 99,
          volume: 123456,
        },
      },
    ]);

    renderWidget();

    expect(await screen.findByText("Range %")).toBeInTheDocument();
    expect(screen.getByText("+20.00%")).toBeInTheDocument();
    expect(screen.getByText("1.2L")).toBeInTheDocument();
  });

  // ── FDC3 channel bus ─────────────────────────────────────────────────────

  it("row click broadcasts on the default (red) channel and legacy readers follow", async () => {
    const { store } = renderWidget();

    // A follower subscribed to the widget's channel sees the broadcast.
    const seen: Array<unknown> = [];
    const unsubscribe = subscribeChannelInstrument(store, DEFAULT_CHANNEL_ID, (i) => seen.push(i));

    await userEvent.click(screen.getByRole("button", { name: "NIFTY" }));

    expect(seen).toEqual([{ symbol: "NIFTY", exchange: "NSE_INDEX" }]);
    expect(store.get(channelInstrumentAtoms[DEFAULT_CHANNEL_ID]))
      .toEqual({ symbol: "NIFTY", exchange: "NSE_INDEX" });
    // The red channel aliases selectedSymbolAtom — unmigrated consumers
    // observe exactly what setSelectedSymbol writers used to set.
    expect(store.get(selectedSymbolAtom)).toEqual({ symbol: "NIFTY", exchange: "NSE_INDEX" });
    unsubscribe();
  });

  it("row click broadcasts on the widget's OWN channel from panel params", async () => {
    mockLocalStorage["flinttrade:watchlists"] = JSON.stringify([
      { id: "t1", name: "Watchlist 1", symbols: [{ symbol: "SBIN", exchange: "NSE" }] },
    ]);
    const { store } = renderWidget({ channel: "fdc3.channel.green" });

    await userEvent.click(screen.getByRole("button", { name: "SBIN" }));

    expect(store.get(channelInstrumentAtoms["fdc3.channel.green"]))
      .toEqual({ symbol: "SBIN", exchange: "NSE" });
    // Nothing leaks onto the default (red) channel.
    expect(store.get(channelInstrumentAtoms[DEFAULT_CHANNEL_ID])).toBeNull();
  });

  it("joined to no channel (channel: 'none') broadcasts nowhere", async () => {
    const { store } = renderWidget({ channel: "none" });

    await userEvent.click(screen.getByRole("button", { name: "NIFTY" }));

    for (const meta of USER_CHANNELS) {
      expect(store.get(channelInstrumentAtoms[meta.id])).toBeNull();
    }
  });

  it("quick trade raises CreateOrder with the same addWidget detail as before", async () => {
    mockLocalStorage["flinttrade:watchlists"] = JSON.stringify([
      { id: "t1", name: "Watchlist 1", symbols: [{ symbol: "SBIN", exchange: "NSE" }] },
    ]);
    const { events, stop } = captureAddWidget();
    const { store } = renderWidget();

    fireEvent.click(screen.getByLabelText("Buy SBIN"));
    fireEvent.click(screen.getByLabelText("Sell SBIN"));

    expect(events).toEqual([
      {
        widgetId: "orderpad",
        title: "Order — SBIN",
        props: { symbol: "SBIN", exchange: "NSE", action: "BUY" },
      },
      {
        widgetId: "orderpad",
        title: "Order — SBIN",
        props: { symbol: "SBIN", exchange: "NSE", action: "SELL" },
      },
    ]);
    // Quick trade also focuses the instrument on the widget's channel.
    expect(store.get(channelInstrumentAtoms[DEFAULT_CHANNEL_ID]))
      .toEqual({ symbol: "SBIN", exchange: "NSE" });
    stop();
  });

  it("quick trade still opens the order ticket when joined to no channel", async () => {
    mockLocalStorage["flinttrade:watchlists"] = JSON.stringify([
      { id: "t1", name: "Watchlist 1", symbols: [{ symbol: "SBIN", exchange: "NSE" }] },
    ]);
    const { events, stop } = captureAddWidget();
    const { store } = renderWidget({ channel: "none" });

    fireEvent.click(screen.getByLabelText("Buy SBIN"));

    expect(events).toEqual([
      {
        widgetId: "orderpad",
        title: "Order — SBIN",
        props: { symbol: "SBIN", exchange: "NSE", action: "BUY" },
      },
    ]);
    // …but the selection broadcast goes nowhere.
    for (const meta of USER_CHANNELS) {
      expect(store.get(channelInstrumentAtoms[meta.id])).toBeNull();
    }
    stop();
  });
});
