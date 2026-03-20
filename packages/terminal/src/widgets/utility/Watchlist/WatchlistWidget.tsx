/**
 * WatchlistWidget — production watchlist for FlintTrade terminal.
 *
 * Features:
 *   - Persisted to localStorage key `flinttrade:watchlist`
 *   - Batch quote polling: 5s market hours, 60s off-hours
 *   - Debounced symbol search (300ms) with dropdown autocomplete
 *   - Per-row sparkline built from last 20 LTP samples
 *   - Right-click context menu to remove a symbol
 *   - Click writes { symbol, exchange } to selectedSymbolAtom (Jotai)
 *   - Dense dark layout matching FlintTrade terminal theme
 */

import { useState, useEffect, useCallback, useRef } from "react";
import {
  Plus, X, Search, MoreVertical, Trash2,
  TrendingUp, TrendingDown,
} from "lucide-react";
import { useSetAtom } from "jotai";
import { selectedSymbolAtom } from "@/atoms/marketAtoms";
import { getMultiQuotes, searchSymbol } from "@/services/api";
import type { Quote, WsInstrument } from "@/types/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface WatchlistItem {
  symbol: string;
  exchange: string;
}

/** Partial quote shape from OpenAlgo — fields may be absent depending on mode */
interface PartialQuote extends Partial<Quote> {
  prev_close?: number;
}

type QuoteMap = Record<string, PartialQuote>;
type SparkMap = Record<string, number[]>;

interface ContextMenuState {
  x: number;
  y: number;
  item: WatchlistItem;
}

interface SearchResult {
  symbol: string;
  exchange: string;
  name?: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LS_KEY = "flinttrade:watchlist";

const DEFAULT_SYMBOLS: WatchlistItem[] = [
  { symbol: "NIFTY",     exchange: "NSE_INDEX" },
  { symbol: "BANKNIFTY", exchange: "NSE_INDEX" },
  { symbol: "SBIN",      exchange: "NSE"       },
  { symbol: "RELIANCE",  exchange: "NSE"       },
  { symbol: "HDFCBANK",  exchange: "NSE"       },
];

/** Max sparkline history samples per symbol */
const SPARK_MAX = 20;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** True during NSE/BSE market hours: Mon–Fri 09:15–15:30 IST. */
function isMarketHours(): boolean {
  const now = new Date();
  const ist = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
  const day = ist.getDay();
  if (day === 0 || day === 6) return false;
  const mins = ist.getHours() * 60 + ist.getMinutes();
  return mins >= 555 && mins <= 930; // 09:15 – 15:30
}

const FMT = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });

function fmtPrice(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return "—";
  return FMT.format(Number(v));
}

function fmtPct(v: number | null | undefined): string | null {
  if (v == null || isNaN(v)) return null;
  const n = Number(v);
  return (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
}

/** Load watchlist from localStorage, fallback to defaults. */
function loadWatchlist(): WatchlistItem[] {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) return parsed as WatchlistItem[];
    }
  } catch {
    // ignore parse errors
  }
  return DEFAULT_SYMBOLS;
}

/** Persist watchlist to localStorage. */
function saveWatchlist(list: WatchlistItem[]): void {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(list));
  } catch {
    // localStorage unavailable
  }
}

// ---------------------------------------------------------------------------
// Sparkline SVG
// ---------------------------------------------------------------------------

interface SparklineProps {
  prices: number[];
  positive: boolean | null;
}

function Sparkline({ prices, positive }: SparklineProps) {
  if (!prices || prices.length < 2) {
    return (
      <div className="w-10 h-4 flex items-center justify-center">
        {positive === true  && <TrendingUp  size={10} className="text-profit" />}
        {positive === false && <TrendingDown size={10} className="text-loss"  />}
        {positive == null  && <span className="text-xxs text-text-muted">—</span>}
      </div>
    );
  }

  const W = 40;
  const H = 16;
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const range = max - min || 1;

  const pts = prices.map((p, i) => {
    const x = (i / (prices.length - 1)) * W;
    const y = H - ((p - min) / range) * H;
    return `${x},${y}`;
  });

  const color = positive === false ? "#ef4444" : "#22c55e";

  return (
    <svg width={W} height={H} className="shrink-0">
      <polyline
        points={pts.join(" ")}
        fill="none"
        stroke={color}
        strokeWidth="1.2"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Search dialog
// ---------------------------------------------------------------------------

interface SearchDialogProps {
  onAdd: (item: WatchlistItem) => void;
  onClose: () => void;
}

function SearchDialog({ onAdd, onClose }: SearchDialogProps) {
  const [query, setQuery]     = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const debounceRef           = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef              = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleQuery = useCallback((val: string) => {
    setQuery(val);
    setError(null);
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (!val.trim()) {
      setResults([]);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const data = await searchSymbol(val.trim());
        // OpenAlgo returns Array<{ symbol, exchange }> — api.ts types it so
        const list = Array.isArray(data) ? (data as SearchResult[]) : [];
        setResults(list.slice(0, 12));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Search failed");
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);
  }, []);

  // Cleanup debounce on unmount
  useEffect(() => () => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
  }, []);

  const handleSelect = useCallback((item: SearchResult) => {
    onAdd({ symbol: item.symbol, exchange: item.exchange });
    onClose();
  }, [onAdd, onClose]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Escape") onClose();
  }, [onClose]);

  return (
    <div
      className="absolute inset-0 z-50 flex flex-col bg-surface-base/90 backdrop-blur-sm"
      onKeyDown={handleKeyDown}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-2 py-1.5 border-b border-border-default bg-surface-card shrink-0">
        <Search size={11} className="text-text-muted shrink-0" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => handleQuery(e.target.value)}
          placeholder="Search symbol... e.g. SBIN, TCS"
          className="flex-1 bg-transparent text-xs text-text-primary placeholder-text-muted focus:outline-none"
        />
        <button
          onClick={onClose}
          className="text-text-muted hover:text-text-primary transition-colors"
          aria-label="Close search"
        >
          <X size={11} />
        </button>
      </div>

      {/* Results */}
      <div className="flex-1 overflow-auto">
        {loading && (
          <div className="px-3 py-2 text-xs text-text-muted">Searching…</div>
        )}
        {error && !loading && (
          <div className="px-3 py-2 text-xs text-loss">{error}</div>
        )}
        {!loading && !error && results.length === 0 && query.trim() && (
          <div className="px-3 py-2 text-xs text-text-muted">No results for "{query}"</div>
        )}
        {!loading && !error && results.length === 0 && !query.trim() && (
          <div className="px-3 py-2 text-xs text-text-muted">Type to search symbols</div>
        )}
        {results.map((item, idx) => (
          <button
            key={`${item.symbol}-${item.exchange}-${idx}`}
            onClick={() => handleSelect(item)}
            className="w-full flex items-center justify-between px-3 py-1.5 hover:bg-surface-hover text-left transition-colors border-b border-border-subtle"
          >
            <div className="flex flex-col min-w-0">
              <span className="text-xs font-medium text-text-primary font-mono truncate">
                {item.symbol}
              </span>
              {item.name && (
                <span className="text-xs text-text-muted truncate">{item.name}</span>
              )}
            </div>
            <span className="text-xs text-text-muted ml-2 shrink-0 font-mono">
              {item.exchange}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Context menu (right-click)
// ---------------------------------------------------------------------------

interface ContextMenuProps {
  x: number;
  y: number;
  symbol: string;
  onRemove: () => void;
  onClose: () => void;
}

function ContextMenu({ x, y, symbol, onRemove, onClose }: ContextMenuProps) {
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) onClose();
    }
    document.addEventListener("mousedown", handle);
    document.addEventListener("contextmenu", handle);
    return () => {
      document.removeEventListener("mousedown", handle);
      document.removeEventListener("contextmenu", handle);
    };
  }, [onClose]);

  return (
    <div
      ref={menuRef}
      className="fixed z-50 bg-surface-card border border-border-default rounded shadow-2xl py-1 min-w-36"
      style={{ top: y, left: x }}
    >
      <div className="px-3 py-1 border-b border-border-subtle mb-1">
        <span className="text-xs text-text-muted font-mono">{symbol}</span>
      </div>
      <button
        onClick={onRemove}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-loss hover:bg-loss/10 transition-colors"
      >
        <Trash2 size={10} />
        Remove
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Symbol row
// ---------------------------------------------------------------------------

interface SymbolRowProps {
  item: WatchlistItem;
  quote: PartialQuote | null;
  sparkPrices: number[];
  onSelect: (item: WatchlistItem) => void;
  onRemove: (e: React.MouseEvent, item: WatchlistItem) => void;
}

function SymbolRow({ item, quote, sparkPrices, onSelect, onRemove }: SymbolRowProps) {
  const ltp       = quote?.ltp    ?? quote?.close ?? null;
  const prevClose = quote?.prev_close ?? quote?.close ?? null;
  const chgAbs    = ltp != null && prevClose != null ? ltp - prevClose : null;
  const chgPct    = chgAbs != null && prevClose ? (chgAbs / prevClose) * 100 : null;
  const isUp      = chgAbs == null ? null : chgAbs >= 0;
  const changeColor = isUp === true ? "text-profit" : isUp === false ? "text-loss" : "text-text-muted";

  return (
    <div
      className="flex items-center gap-1.5 px-2 py-1.5 hover:bg-surface-hover cursor-pointer border-b border-border-subtle transition-colors group"
      onClick={() => onSelect(item)}
      onContextMenu={(e) => {
        e.preventDefault();
        onRemove(e, item);
      }}
      title={`${item.symbol} · ${item.exchange} — right-click to remove`}
    >
      {/* Symbol + Exchange */}
      <div className="flex flex-col min-w-0 flex-1">
        <span className="text-xs font-medium text-text-primary font-mono leading-tight truncate">
          {item.symbol}
        </span>
        <span className="text-xxs text-text-muted leading-tight">{item.exchange}</span>
      </div>

      {/* Sparkline */}
      <Sparkline prices={sparkPrices} positive={isUp} />

      {/* Price block */}
      <div className="flex flex-col items-end shrink-0 min-w-16">
        <span className="text-xs font-mono tabular-nums font-semibold text-text-primary leading-tight">
          {fmtPrice(ltp)}
        </span>
        <span className={`text-xxs font-mono tabular-nums leading-tight ${changeColor}`}>
          {chgPct != null ? fmtPct(chgPct) : "—"}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

interface WatchlistWidgetProps {
  /** FlexLayout node reference (unused directly but kept for API compat) */
  node?: unknown;
}

export default function WatchlistWidget({ node: _node }: WatchlistWidgetProps) {
  const [watchlist, setWatchlist]       = useState<WatchlistItem[]>(() => loadWatchlist());
  const [quotes, setQuotes]             = useState<QuoteMap>({});
  const [sparkHistory, setSparkHistory] = useState<SparkMap>({});
  const [showSearch, setShowSearch]     = useState(false);
  const [showMenu, setShowMenu]         = useState(false);
  const [contextMenu, setContextMenu]   = useState<ContextMenuState | null>(null);
  const [fetchError, setFetchError]     = useState<string | null>(null);
  const pollRef                         = useRef<ReturnType<typeof setTimeout> | null>(null);
  const menuRef                         = useRef<HTMLDivElement | null>(null);

  // Jotai atom setter — replaces dataBus.publish("watchlist:select", ...)
  const setSelectedSymbol = useSetAtom(selectedSymbolAtom);

  // Persist whenever watchlist changes
  useEffect(() => {
    saveWatchlist(watchlist);
  }, [watchlist]);

  // ---------------------------------------------------------------------------
  // Quote polling
  // ---------------------------------------------------------------------------

  const fetchQuotes = useCallback(async () => {
    if (watchlist.length === 0) return;

    const symbols: WsInstrument[] = watchlist.map((w) => ({
      symbol: w.symbol,
      exchange: w.exchange,
    }));

    try {
      const data = await getMultiQuotes(symbols);
      setFetchError(null);

      // Normalise response — OpenAlgo multiquotes returns Quote[]
      if (Array.isArray(data)) {
        const next: QuoteMap = {};
        const histNext: SparkMap = {};

        data.forEach((q: PartialQuote, idx: number) => {
          const item = watchlist[idx];
          if (!item) return;
          const key = `${item.symbol}:${item.exchange}`;
          next[key] = q;
          const ltp = q?.ltp ?? q?.close ?? null;
          if (ltp != null) {
            histNext[key] = [
              ...(sparkHistory[key] ?? []).slice(-(SPARK_MAX - 1)),
              Number(ltp),
            ];
          }
        });

        setQuotes((prev) => ({ ...prev, ...next }));
        setSparkHistory((prev) => ({ ...prev, ...histNext }));
      } else if (data && typeof data === "object") {
        // Object form keyed by symbol or "EXCHANGE:SYMBOL"
        const dataObj = data as Record<string, PartialQuote>;
        const next: QuoteMap = {};
        const histNext: SparkMap = {};

        watchlist.forEach((item) => {
          const key = `${item.symbol}:${item.exchange}`;
          const q =
            dataObj[key] ??
            dataObj[`${item.exchange}:${item.symbol}`] ??
            dataObj[item.symbol] ??
            null;

          if (q) {
            next[key] = q;
            const ltp = q?.ltp ?? q?.close ?? null;
            if (ltp != null) {
              histNext[key] = [
                ...(sparkHistory[key] ?? []).slice(-(SPARK_MAX - 1)),
                Number(ltp),
              ];
            }
          }
        });

        setQuotes((prev) => ({ ...prev, ...next }));
        setSparkHistory((prev) => ({ ...prev, ...histNext }));
      }
    } catch (err) {
      setFetchError(err instanceof Error ? err.message : "Quote fetch failed");
    }
  }, [watchlist, sparkHistory]);

  // Schedule polling — 5s market hours, 60s off-hours
  useEffect(() => {
    void fetchQuotes();

    function schedule() {
      const delay = isMarketHours() ? 5000 : 60000;
      pollRef.current = setTimeout(() => {
        void fetchQuotes();
        schedule();
      }, delay);
    }

    schedule();
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [fetchQuotes]);

  // ---------------------------------------------------------------------------
  // Add / remove symbols
  // ---------------------------------------------------------------------------

  const handleAdd = useCallback((item: WatchlistItem) => {
    setWatchlist((prev) => {
      const exists = prev.some(
        (w) => w.symbol === item.symbol && w.exchange === item.exchange,
      );
      if (exists) return prev;
      return [...prev, { symbol: item.symbol, exchange: item.exchange }];
    });
  }, []);

  const handleRemove = useCallback((item: WatchlistItem) => {
    setWatchlist((prev) =>
      prev.filter((w) => !(w.symbol === item.symbol && w.exchange === item.exchange)),
    );
    setContextMenu(null);
  }, []);

  const handleClearAll = useCallback(() => {
    setWatchlist([]);
    setShowMenu(false);
  }, []);

  const handleResetDefaults = useCallback(() => {
    setWatchlist(DEFAULT_SYMBOLS);
    setShowMenu(false);
  }, []);

  // ---------------------------------------------------------------------------
  // Context menu (right-click)
  // ---------------------------------------------------------------------------

  const openContextMenu = useCallback((e: React.MouseEvent, item: WatchlistItem) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY, item });
  }, []);

  const closeContextMenu = useCallback(() => setContextMenu(null), []);

  // ---------------------------------------------------------------------------
  // Symbol select — write to Jotai selectedSymbolAtom
  // ---------------------------------------------------------------------------

  const handleSelect = useCallback((item: WatchlistItem) => {
    setSelectedSymbol({ symbol: item.symbol, exchange: item.exchange });
  }, [setSelectedSymbol]);

  // ---------------------------------------------------------------------------
  // Close overflow menu on outside click
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (!showMenu) return;
    function handle(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowMenu(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [showMenu]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const count = watchlist.length;

  return (
    <div className="h-full flex flex-col bg-surface-base text-text-primary overflow-hidden relative">

      {/* HEADER */}
      <div className="flex items-center gap-1.5 px-2 py-1 border-b border-border-default bg-surface-card shrink-0">
        <span className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
          Watchlist
        </span>

        {count > 0 && (
          <span className="text-xxs font-mono bg-surface-hover text-text-muted border border-border-default rounded px-1 leading-4">
            {count}
          </span>
        )}

        {fetchError && (
          <span
            title={fetchError}
            className="w-1.5 h-1.5 rounded-full bg-loss shrink-0"
          />
        )}

        <div className="flex-1" />

        <button
          onClick={() => setShowSearch(true)}
          title="Add symbol"
          className="w-5 h-5 flex items-center justify-center text-text-muted hover:text-text-primary hover:bg-surface-hover rounded transition-colors"
          aria-label="Add symbol"
        >
          <Plus size={11} />
        </button>

        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setShowMenu((v) => !v)}
            title="More options"
            className="w-5 h-5 flex items-center justify-center text-text-muted hover:text-text-primary hover:bg-surface-hover rounded transition-colors"
            aria-label="More options"
          >
            <MoreVertical size={11} />
          </button>

          {showMenu && (
            <div className="absolute right-0 top-6 z-40 bg-surface-card border border-border-default rounded shadow-2xl py-1 min-w-40">
              <button
                onClick={() => { setShowSearch(true); setShowMenu(false); }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
              >
                <Plus size={10} />
                Add symbol
              </button>
              <button
                onClick={handleResetDefaults}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
              >
                <TrendingUp size={10} />
                Reset to defaults
              </button>
              <div className="border-t border-border-subtle my-1" />
              <button
                onClick={handleClearAll}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-loss hover:bg-loss/10 transition-colors"
              >
                <Trash2 size={10} />
                Clear all
              </button>
            </div>
          )}
        </div>
      </div>

      {/* SYMBOL LIST */}
      <div className="flex-1 overflow-auto">
        {watchlist.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center gap-3 px-4">
            <TrendingUp size={24} className="text-text-muted" />
            <div className="text-center">
              <p className="text-xs text-text-secondary">Add symbols to your watchlist</p>
              <p className="text-xs text-text-muted mt-0.5">Track prices in real-time</p>
            </div>
            <button
              onClick={() => setShowSearch(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-accent/10 hover:bg-accent/20 text-accent border border-accent/30 rounded text-xs font-medium transition-colors"
            >
              <Plus size={11} />
              Add symbol
            </button>
          </div>
        ) : (
          watchlist.map((item) => {
            const key = `${item.symbol}:${item.exchange}`;
            return (
              <SymbolRow
                key={key}
                item={item}
                quote={quotes[key] ?? null}
                sparkPrices={sparkHistory[key] ?? []}
                onSelect={handleSelect}
                onRemove={openContextMenu}
              />
            );
          })
        )}
      </div>

      {/* SEARCH DIALOG (overlaid) */}
      {showSearch && (
        <SearchDialog
          onAdd={handleAdd}
          onClose={() => setShowSearch(false)}
        />
      )}

      {/* CONTEXT MENU */}
      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          symbol={contextMenu.item.symbol}
          onRemove={() => handleRemove(contextMenu.item)}
          onClose={closeContextMenu}
        />
      )}
    </div>
  );
}
