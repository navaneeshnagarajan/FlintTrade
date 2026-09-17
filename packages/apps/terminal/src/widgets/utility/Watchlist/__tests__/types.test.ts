import { describe, it, expect, beforeEach } from "vitest";
import {
  addSymbolToWatchlist,
  loadTabs,
  saveTabs,
  resolveWatchlistQuoteFields,
  LS_KEY_LEGACY,
} from "../types";

// ---------------------------------------------------------------------------
// addSymbolToWatchlist — the entry point other widgets use. The Scanner used
// to write straight to the LEGACY key, which loadTabs only reads when the
// canonical multi-tab key is absent, so on a migrated install the symbol
// silently never appeared while the button reported success.
// ---------------------------------------------------------------------------

describe("addSymbolToWatchlist", () => {
  beforeEach(() => localStorage.clear());

  it("writes where the watchlist actually reads, and never to the legacy key", () => {
    expect(addSymbolToWatchlist({ symbol: "SBIN", exchange: "NSE" })).toBe(true);

    // The contract that matters: the watchlist's own loader sees it.
    expect(loadTabs()[0].symbols).toContainEqual({ symbol: "SBIN", exchange: "NSE" });
    // The legacy single-list key is migration-only and must stay untouched —
    // writing there is what made the Scanner's button a silent no-op.
    expect(localStorage.getItem(LS_KEY_LEGACY)).toBeNull();
  });

  it("is visible to the watchlist after an existing multi-tab store is seeded", () => {
    saveTabs([{ id: "t1", name: "Watchlist 1", symbols: [{ symbol: "NIFTY", exchange: "NSE_INDEX" }] }]);

    addSymbolToWatchlist({ symbol: "RELIANCE", exchange: "NSE" });

    const symbols = loadTabs()[0].symbols;
    expect(symbols).toContainEqual({ symbol: "NIFTY", exchange: "NSE_INDEX" });
    expect(symbols).toContainEqual({ symbol: "RELIANCE", exchange: "NSE" });
  });

  it("does not duplicate a symbol already on the list", () => {
    addSymbolToWatchlist({ symbol: "SBIN", exchange: "NSE" });
    addSymbolToWatchlist({ symbol: "SBIN", exchange: "NSE" });

    const matches = loadTabs()[0].symbols.filter((s) => s.symbol === "SBIN");
    expect(matches).toHaveLength(1);
  });
});

describe("resolveWatchlistQuoteFields", () => {
  it("prefers the ticker tick-atom LTP and prevClose over a REST quote", () => {
    const fields = resolveWatchlistQuoteFields(
      { symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 24150, prevClose: 24000, pct: 0.625 },
      { symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 1, prev_close: 1 },
    );
    expect(fields.ltp).toBe(24150);
    expect(fields.prevClose).toBe(24000);
    expect(fields.chgAbs).toBe(150);
    expect(fields.chgPct).toBeCloseTo(0.625);
  });

  it("falls back to the REST quote when no tick has arrived", () => {
    const fields = resolveWatchlistQuoteFields(null, {
      symbol: "SBIN",
      exchange: "NSE",
      ltp: 780,
      prev_close: 770,
    });
    expect(fields.ltp).toBe(780);
    expect(fields.chgPct).toBeCloseTo((10 / 770) * 100);
  });

  it("returns nulls when neither a tick nor a REST quote is present", () => {
    expect(resolveWatchlistQuoteFields(null, null)).toEqual({
      ltp: null,
      prevClose: null,
      chgAbs: null,
      chgPct: null,
    });
  });
});
