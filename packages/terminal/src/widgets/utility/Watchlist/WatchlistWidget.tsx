/**
 * WatchlistWidget — multi-tab production watchlist for FlintTrade terminal.
 *
 * Features:
 *   - Up to 5 watchlist tabs, each with its own symbol list
 *   - Tab bar: compact pills, active tab highlighted with accent colour
 *   - "+" button to create a new tab
 *   - Right-click tab to Rename, Duplicate, or Delete
 *   - Persisted to localStorage key `flinttrade:watchlists` (all tabs)
 *   - Backward-compatible: migrates legacy `flinttrade:watchlist` key
 *   - Batch quote polling: 5s market hours, 60s off-hours
 *   - Debounced symbol search (300ms) with dropdown autocomplete
 *   - Per-row sparkline built from last 20 LTP samples
 *   - Right-click context menu on symbol to remove
 *   - Click writes { symbol, exchange } to selectedSymbolAtom (Jotai)
 *   - Dense dark layout matching FlintTrade terminal theme
 */

import { useState, useEffect, useCallback, useRef, useMemo, memo } from "react";
import {
  Plus, X, Search, MoreVertical, Trash2,
  TrendingUp, TrendingDown, Pencil, Copy,
} from "lucide-react";
import { useSetAtom } from "jotai";
import { selectedSymbolAtom } from "@/atoms/marketAtoms";
import { getMultiQuotes, searchSymbol } from "@/services/api";
import type { Quote, WsInstrument } from "@/types/api";
import { isMarketHours } from "@/lib/market";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface WatchlistItem {
  symbol:   string;
  exchange: string;
}

/** Partial quote shape from OpenAlgo — fields may be absent depending on mode */
interface PartialQuote extends Partial<Quote> {
  prev_close?: number;
}

type QuoteMap  = Record<string, PartialQuote>;
type SparkMap  = Record<string, number[]>;

interface SymbolContextMenuState {
  x:    number;
  y:    number;
  item: WatchlistItem;
}

interface TabContextMenuState {
  x:   number;
  y:   number;
  idx: number;
}

interface SearchResult {
  symbol:   string;
  exchange: string;
  name?:    string;
}

/** One watchlist tab */
interface WatchlistTab {
  id:      string;
  name:    string;
  symbols: WatchlistItem[];
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LS_KEY_MULTI  = "flinttrade:watchlists";
const LS_KEY_LEGACY = "flinttrade:watchlist";

const MAX_TABS = 5;

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

const FMT = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
});

function fmtPrice(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return "—";
  return FMT.format(Number(v));
}

function fmtPct(v: number | null | undefined): string | null {
  if (v == null || isNaN(v)) return null;
  const n = Number(v);
  return (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
}

function generateId(): string {
  return Math.random().toString(36).slice(2, 9);
}

function makeDefaultTab(): WatchlistTab {
  return { id: generateId(), name: "Watchlist 1", symbols: DEFAULT_SYMBOLS };
}

/** Load all watchlist tabs from localStorage. Migrates legacy single-list format. */
function loadTabs(): WatchlistTab[] {
  try {
    const raw = localStorage.getItem(LS_KEY_MULTI);
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) return parsed as WatchlistTab[];
    }
    // Migrate legacy single-list
    const legacy = localStorage.getItem(LS_KEY_LEGACY);
    if (legacy) {
      const items: unknown = JSON.parse(legacy);
      if (Array.isArray(items) && items.length > 0) {
        return [{ id: generateId(), name: "Watchlist 1", symbols: items as WatchlistItem[] }];
      }
    }
  } catch {
    // ignore parse errors
  }
  return [makeDefaultTab()];
}

/** Persist all watchlist tabs to localStorage. */
function saveTabs(tabs: WatchlistTab[]): void {
  try {
    localStorage.setItem(LS_KEY_MULTI, JSON.stringify(tabs));
  } catch {
    // localStorage unavailable
  }
}

// ---------------------------------------------------------------------------
// Sparkline SVG
// ---------------------------------------------------------------------------

interface SparklineProps {
  prices:   number[];
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
  const min   = Math.min(...prices);
  const max   = Math.max(...prices);
  const range = max - min || 1;

  const pts = prices.map((p, i) => {
    const x = (i / (prices.length - 1)) * W;
    const y = H - ((p - min) / range) * H;
    return `${x},${y}`;
  });

  const color = positive === false ? "#ef4444" : "#22c55e";

  return (
    <svg
      width={W}
      height={H}
      className="shrink-0"
      role="img"
      aria-label={`Price trend: ${positive === false ? "falling" : "rising"}`}
    >
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
  onAdd:    (item: WatchlistItem) => void;
  onClose:  () => void;
}

function SearchDialog({ onAdd, onClose }: SearchDialogProps) {
  const [query,   setQuery]   = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);
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
      role="dialog"
      aria-modal="true"
      aria-label="Search symbols"
      className="absolute inset-0 z-50 flex flex-col bg-surface-base/90 backdrop-blur-sm"
      onKeyDown={handleKeyDown}
    >
      <div className="flex items-center gap-2 px-2 py-1.5 border-b border-border-default bg-surface-card shrink-0">
        <Search size={11} className="text-text-muted shrink-0" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => handleQuery(e.target.value)}
          placeholder="Search symbol… e.g. SBIN, TCS"
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

      <div className="flex-1 overflow-auto">
        {loading && <div className="px-3 py-2 text-xs text-text-muted">Searching…</div>}
        {error && !loading && <div className="px-3 py-2 text-xs text-loss">{error}</div>}
        {!loading && !error && results.length === 0 && query.trim() && (
          <div className="px-3 py-2 text-xs text-text-muted">No results for &quot;{query}&quot;</div>
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
// Symbol context menu (right-click on symbol row)
// ---------------------------------------------------------------------------

interface SymbolContextMenuProps {
  x:        number;
  y:        number;
  symbol:   string;
  onRemove: () => void;
  onClose:  () => void;
}

function SymbolContextMenu({ x, y, symbol, onRemove, onClose }: SymbolContextMenuProps) {
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
      role="menu"
      aria-label={`Actions for ${symbol}`}
      className="fixed z-50 bg-surface-card border border-border-default rounded shadow-2xl py-1 min-w-36"
      style={{ top: y, left: x }}
    >
      <div className="px-3 py-1 border-b border-border-subtle mb-1">
        <span className="text-xs text-text-muted font-mono">{symbol}</span>
      </div>
      <button
        role="menuitem"
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
// Tab context menu (right-click on tab pill)
// ---------------------------------------------------------------------------

interface TabContextMenuProps {
  x:           number;
  y:           number;
  tabName:     string;
  canDelete:   boolean;
  onRename:    () => void;
  onDuplicate: () => void;
  onDelete:    () => void;
  onClose:     () => void;
}

function TabContextMenu({
  x, y, tabName, canDelete, onRename, onDuplicate, onDelete, onClose,
}: TabContextMenuProps) {
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) onClose();
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [onClose]);

  return (
    <div
      ref={menuRef}
      role="menu"
      aria-label={`Tab actions for ${tabName}`}
      className="fixed z-50 bg-surface-card border border-border-default rounded shadow-2xl py-1 min-w-40"
      style={{ top: y, left: x }}
    >
      <div className="px-3 py-1 border-b border-border-subtle mb-1">
        <span className="text-xs text-text-muted truncate">{tabName}</span>
      </div>
      <button
        role="menuitem"
        onClick={onRename}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
      >
        <Pencil size={10} />
        Rename
      </button>
      <button
        role="menuitem"
        onClick={onDuplicate}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
      >
        <Copy size={10} />
        Duplicate
      </button>
      {canDelete && (
        <>
          <div className="border-t border-border-subtle my-1" />
          <button
            role="menuitem"
            onClick={onDelete}
            className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-loss hover:bg-loss/10 transition-colors"
          >
            <Trash2 size={10} />
            Delete
          </button>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Rename inline input
// ---------------------------------------------------------------------------

interface RenameInputProps {
  initialValue: string;
  onConfirm:    (name: string) => void;
  onCancel:     () => void;
}

function RenameInput({ initialValue, onConfirm, onCancel }: RenameInputProps) {
  const [value, setValue] = useState(initialValue);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const commit = useCallback(() => {
    const trimmed = value.trim();
    if (trimmed) onConfirm(trimmed);
    else onCancel();
  }, [value, onConfirm, onCancel]);

  const handleKey = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter")  commit();
    if (e.key === "Escape") onCancel();
  }, [commit, onCancel]);

  return (
    <input
      ref={inputRef}
      type="text"
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={handleKey}
      className="w-24 h-4 bg-surface-elevated border border-accent/50 text-text-primary text-xs rounded px-1 focus:outline-none"
      maxLength={20}
    />
  );
}

// ---------------------------------------------------------------------------
// Symbol row
// ---------------------------------------------------------------------------

interface SymbolRowProps {
  item:        WatchlistItem;
  quote:       PartialQuote | null;
  sparkPrices: number[];
  onSelect:    (item: WatchlistItem) => void;
  onRemove:    (e: React.MouseEvent, item: WatchlistItem) => void;
}

function SymbolRow({ item, quote, sparkPrices, onSelect, onRemove }: SymbolRowProps) {
  const ltp       = quote?.ltp    ?? quote?.close ?? null;
  const prevClose = quote?.prev_close ?? quote?.close ?? null;
  const chgAbs    = ltp != null && prevClose != null ? ltp - prevClose : null;
  const chgPct    = chgAbs != null && prevClose ? (chgAbs / prevClose) * 100 : null;
  const isUp      = chgAbs == null ? null : chgAbs >= 0;
  const changeColor = isUp === true ? "text-profit" : isUp === false ? "text-loss" : "text-text-muted";

  return (
    <button
      type="button"
      aria-label={item.symbol}
      className="w-full text-left flex items-center gap-1.5 px-2 py-1.5 hover:bg-surface-hover cursor-pointer border-b border-border-subtle transition-colors group"
      onClick={() => onSelect(item)}
      onContextMenu={(e) => {
        e.preventDefault();
        onRemove(e, item);
      }}
      onKeyDown={(e) => {
        if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) {
          e.preventDefault();
          const rect = e.currentTarget.getBoundingClientRect();
          onRemove(
            {
              clientX: rect.left + rect.width / 2,
              clientY: rect.top + rect.height / 2,
              preventDefault: () => {},
            } as React.MouseEvent,
            item,
          );
        }
      }}
      title={`${item.symbol} · ${item.exchange} — right-click or Shift+F10 to remove`}
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
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

interface WatchlistWidgetProps {
  node?: unknown;
}

function WatchlistWidget({ node: _node }: WatchlistWidgetProps) {
  const [tabs, setTabs]               = useState<WatchlistTab[]>(() => loadTabs());
  const [activeTabIdx, setActiveTabIdx] = useState(0);
  const [quotes, setQuotes]           = useState<QuoteMap>({});
  const [sparkHistory, setSparkHistory] = useState<SparkMap>({});
  const [showSearch, setShowSearch]   = useState(false);
  const [showMenu, setShowMenu]       = useState(false);
  const [symbolCtxMenu, setSymbolCtxMenu] = useState<SymbolContextMenuState | null>(null);
  const [tabCtxMenu, setTabCtxMenu]   = useState<TabContextMenuState | null>(null);
  const [renamingIdx, setRenamingIdx] = useState<number | null>(null);
  const [fetchError, setFetchError]   = useState<string | null>(null);
  const pollRef                       = useRef<ReturnType<typeof setTimeout> | null>(null);
  const menuRef                       = useRef<HTMLDivElement | null>(null);

  const setSelectedSymbol = useSetAtom(selectedSymbolAtom);

  // Keep active index within bounds when tabs change
  useEffect(() => {
    setActiveTabIdx((prev) => Math.min(prev, tabs.length - 1));
  }, [tabs.length]);

  // Persist whenever tabs change
  useEffect(() => {
    saveTabs(tabs);
  }, [tabs]);

  const activeTab = tabs[activeTabIdx] ?? tabs[0];
  const watchlist = activeTab?.symbols ?? [];

  // ---------------------------------------------------------------------------
  // Quote polling
  // ---------------------------------------------------------------------------

  const watchlistRef = useRef(watchlist);
  useEffect(() => {
    watchlistRef.current = watchlist;
  }, [watchlist]);

  const instrumentsMemo = useMemo(
    () => watchlist.map((w): WsInstrument => ({ symbol: w.symbol, exchange: w.exchange })),
    [watchlist],
  );
  const instrumentsRef = useRef(instrumentsMemo);
  useEffect(() => {
    instrumentsRef.current = instrumentsMemo;
  }, [instrumentsMemo]);

  const fetchQuotes = useCallback(async () => {
    const currentWatchlist = watchlistRef.current;
    const symbols = instrumentsRef.current;
    if (symbols.length === 0) return;

    try {
      const data = await getMultiQuotes(symbols);
      setFetchError(null);

      if (Array.isArray(data)) {
        const next: QuoteMap = {};
        setSparkHistory((prevSpark) => {
          const histNext: SparkMap = { ...prevSpark };
          data.forEach((q: PartialQuote, idx: number) => {
            const item = currentWatchlist[idx];
            if (!item) return;
            const key = `${item.symbol}:${item.exchange}`;
            next[key] = q;
            const ltp = q?.ltp ?? q?.close ?? null;
            if (ltp != null) {
              histNext[key] = [...(prevSpark[key] ?? []).slice(-(SPARK_MAX - 1)), Number(ltp)];
            }
          });
          return histNext;
        });
        setQuotes((prev) => ({ ...prev, ...next }));
      } else if (data && typeof data === "object") {
        const dataObj = data as Record<string, PartialQuote>;
        const next: QuoteMap = {};
        setSparkHistory((prevSpark) => {
          const histNext: SparkMap = { ...prevSpark };
          currentWatchlist.forEach((item) => {
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
                histNext[key] = [...(prevSpark[key] ?? []).slice(-(SPARK_MAX - 1)), Number(ltp)];
              }
            }
          });
          return histNext;
        });
        setQuotes((prev) => ({ ...prev, ...next }));
      }
    } catch (err) {
      setFetchError(err instanceof Error ? err.message : "Quote fetch failed");
    }
  }, []);

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchQuotes, instrumentsMemo]);

  // ---------------------------------------------------------------------------
  // Tab management
  // ---------------------------------------------------------------------------

  const handleAddTab = useCallback(() => {
    if (tabs.length >= MAX_TABS) return;
    setTabs((prev) => {
      const n = prev.length + 1;
      return [...prev, { id: generateId(), name: `Watchlist ${n}`, symbols: [] }];
    });
    setActiveTabIdx(tabs.length); // switch to new tab
  }, [tabs.length]);

  const handleRenameTab = useCallback((idx: number, newName: string) => {
    setTabs((prev) =>
      prev.map((t, i) => (i === idx ? { ...t, name: newName } : t)),
    );
    setRenamingIdx(null);
    setTabCtxMenu(null);
  }, []);

  const handleDuplicateTab = useCallback((idx: number) => {
    if (tabs.length >= MAX_TABS) return;
    setTabs((prev) => {
      const src = prev[idx];
      if (!src) return prev;
      const copy: WatchlistTab = {
        id:      generateId(),
        name:    `${src.name} (copy)`,
        symbols: [...src.symbols],
      };
      const next = [...prev];
      next.splice(idx + 1, 0, copy);
      return next;
    });
    setActiveTabIdx(idx + 1);
    setTabCtxMenu(null);
  }, [tabs.length]);

  const handleDeleteTab = useCallback((idx: number) => {
    if (tabs.length <= 1) return;
    setTabs((prev) => prev.filter((_, i) => i !== idx));
    setActiveTabIdx((prev) => Math.min(prev, tabs.length - 2));
    setTabCtxMenu(null);
  }, [tabs.length]);

  // ---------------------------------------------------------------------------
  // Symbol management (add / remove on the active tab)
  // ---------------------------------------------------------------------------

  const handleAdd = useCallback((item: WatchlistItem) => {
    setTabs((prev) =>
      prev.map((tab, i) => {
        if (i !== activeTabIdx) return tab;
        const exists = tab.symbols.some(
          (w) => w.symbol === item.symbol && w.exchange === item.exchange,
        );
        if (exists) return tab;
        return { ...tab, symbols: [...tab.symbols, { symbol: item.symbol, exchange: item.exchange }] };
      }),
    );
  }, [activeTabIdx]);

  const handleRemoveSymbol = useCallback((item: WatchlistItem) => {
    setTabs((prev) =>
      prev.map((tab, i) => {
        if (i !== activeTabIdx) return tab;
        return {
          ...tab,
          symbols: tab.symbols.filter(
            (w) => !(w.symbol === item.symbol && w.exchange === item.exchange),
          ),
        };
      }),
    );
    setSymbolCtxMenu(null);
  }, [activeTabIdx]);

  const handleClearAll = useCallback(() => {
    setTabs((prev) =>
      prev.map((tab, i) => (i !== activeTabIdx ? tab : { ...tab, symbols: [] })),
    );
    setShowMenu(false);
  }, [activeTabIdx]);

  const handleResetDefaults = useCallback(() => {
    setTabs((prev) =>
      prev.map((tab, i) => (i !== activeTabIdx ? tab : { ...tab, symbols: DEFAULT_SYMBOLS })),
    );
    setShowMenu(false);
  }, [activeTabIdx]);

  // ---------------------------------------------------------------------------
  // Context menus
  // ---------------------------------------------------------------------------

  const openSymbolCtxMenu = useCallback((e: React.MouseEvent, item: WatchlistItem) => {
    e.preventDefault();
    setSymbolCtxMenu({ x: e.clientX, y: e.clientY, item });
  }, []);

  const openTabCtxMenu = useCallback((e: React.MouseEvent, idx: number) => {
    e.preventDefault();
    setTabCtxMenu({ x: e.clientX, y: e.clientY, idx });
  }, []);

  const handleSelect = useCallback((item: WatchlistItem) => {
    setSelectedSymbol({ symbol: item.symbol, exchange: item.exchange });
  }, [setSelectedSymbol]);

  // Close overflow menu on outside click
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
    <div
      className="h-full flex flex-col bg-surface-base text-text-primary overflow-hidden relative"
      data-tour-target="watchlist"
    >
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
          <span title={fetchError} className="w-1.5 h-1.5 rounded-full bg-loss shrink-0" />
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
            <div
              role="menu"
              className="absolute right-0 top-6 z-40 bg-surface-card border border-border-default rounded shadow-2xl py-1 min-w-40"
            >
              <button
                role="menuitem"
                onClick={() => { setShowSearch(true); setShowMenu(false); }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
              >
                <Plus size={10} />
                Add symbol
              </button>
              <button
                role="menuitem"
                onClick={handleResetDefaults}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
              >
                <TrendingUp size={10} />
                Reset to defaults
              </button>
              <div className="border-t border-border-subtle my-1" />
              <button
                role="menuitem"
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

      {/* TAB BAR */}
      <div
        className="flex items-center gap-1 px-2 py-1 border-b border-border-default bg-surface-card shrink-0 overflow-x-auto scrollbar-none"
        role="tablist"
        aria-label="Watchlist tabs"
      >
        {tabs.map((tab, idx) => (
          <div key={tab.id} className="shrink-0 flex items-center">
            {renamingIdx === idx ? (
              <RenameInput
                initialValue={tab.name}
                onConfirm={(name) => handleRenameTab(idx, name)}
                onCancel={() => setRenamingIdx(null)}
              />
            ) : (
              <button
                role="tab"
                aria-selected={idx === activeTabIdx}
                onClick={() => setActiveTabIdx(idx)}
                onContextMenu={(e) => openTabCtxMenu(e, idx)}
                className={`text-xs px-2 py-0.5 rounded transition-colors whitespace-nowrap ${
                  idx === activeTabIdx
                    ? "bg-accent/20 text-accent border border-accent/40"
                    : "text-text-muted hover:text-text-primary hover:bg-surface-hover border border-transparent"
                }`}
                title="Right-click for options"
              >
                {tab.name}
              </button>
            )}
          </div>
        ))}

        {tabs.length < MAX_TABS && (
          <button
            onClick={handleAddTab}
            title="New watchlist"
            aria-label="Add watchlist tab"
            className="shrink-0 w-5 h-5 flex items-center justify-center text-text-muted hover:text-accent hover:bg-surface-hover rounded transition-colors border border-transparent hover:border-accent/30"
          >
            <Plus size={10} />
          </button>
        )}
      </div>

      {/* SYMBOL LIST */}
      <div className="flex-1 overflow-auto">
        {watchlist.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center gap-3 px-4">
            <TrendingUp size={24} className="text-text-muted" />
            <div className="text-center">
              <p className="text-xs text-text-secondary">Add symbols to {activeTab?.name ?? "watchlist"}</p>
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
                onRemove={openSymbolCtxMenu}
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

      {/* SYMBOL CONTEXT MENU */}
      {symbolCtxMenu && (
        <SymbolContextMenu
          x={symbolCtxMenu.x}
          y={symbolCtxMenu.y}
          symbol={symbolCtxMenu.item.symbol}
          onRemove={() => handleRemoveSymbol(symbolCtxMenu.item)}
          onClose={() => setSymbolCtxMenu(null)}
        />
      )}

      {/* TAB CONTEXT MENU */}
      {tabCtxMenu && (
        <TabContextMenu
          x={tabCtxMenu.x}
          y={tabCtxMenu.y}
          tabName={tabs[tabCtxMenu.idx]?.name ?? ""}
          canDelete={tabs.length > 1}
          onRename={() => { setRenamingIdx(tabCtxMenu.idx); setTabCtxMenu(null); }}
          onDuplicate={() => handleDuplicateTab(tabCtxMenu.idx)}
          onDelete={() => handleDeleteTab(tabCtxMenu.idx)}
          onClose={() => setTabCtxMenu(null)}
        />
      )}
    </div>
  );
}

export default memo(WatchlistWidget);
