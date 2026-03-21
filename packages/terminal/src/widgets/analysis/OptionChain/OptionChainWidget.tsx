/**
 * OptionChainWidget — production-grade option chain for FlintTrade terminal.
 *
 * Features:
 *   - Searchable symbol combobox (cmdk) — type to find any F&O stock
 *   - Exchange selector, first-5 expiry buttons, view tabs
 *   - Spot LTP, change, change% (green/red arrow), PCR badge (bullish/bearish/neutral)
 *   - Three view tabs: LTP | OI | GREEKS (Delta/Gamma/Theta/Vega/IV)
 *   - OI interpretation badges: Long Build Up / Short Covering / Long Unwinding / Short Build Up
 *   - Scrollable chain table: 10 strikes above ATM, ATM row highlighted (gold tint), 10 below
 *   - Buy/Sell mini buttons per strike (calls + puts)
 *   - BASKET toggle — select strikes, badge count, basket panel
 *   - Color-coded change%, OI bars, ATM accent border
 *   - Auto-refresh: 3 s market hours, 30 s off-hours
 *   - Dense layout: text-xs data, text-xs headers, font-mono numbers
 *   - Glide theme uses design token hex values (surface/border/text tokens)
 */

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSyntheticFuture } from "@/hooks/useSyntheticFuture";
import DataEditor, {
  type GridColumn,
  type GridCell,
  GridCellKind,
  type DataEditorRef,
  type Item,
  type Theme,
} from "@glideapps/glide-data-grid";
import "@glideapps/glide-data-grid/dist/index.css";
import {
  RefreshCw,
  ChevronDown,
  TrendingUp,
  TrendingDown,
  AlertCircle,
  ShoppingBasket,
  Search,
  X,
  Loader2,
} from "lucide-react";
import { getExpiry, getInstruments, getOptionChain, getOptionSymbol, getQuotes, getSymbol, placeOrder, searchSymbol } from "../../../services/api";
import type { Quote } from "../../../types/api";
import { isMarketHours } from "@/lib/market";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FlexLayoutNode {
  getId?: () => string;
}

interface SymbolDef {
  label: string;
  exchange: string;
  spotSymbol: string;
  spotExchange: string;
}

interface SymbolSearchResult {
  symbol: string;
  exchange: string;
}

/** Shape returned by getInstruments() */
interface InstrumentRecord {
  symbol: string;
  name: string;
  exchange: string;
  instrumenttype: string;
  lotsize: number;
  tick_size: number;
  token: string;
}

/** Exchanges that have option chains */
const OPTION_CHAIN_EXCHANGES = new Set(["NFO", "BFO", "MCX", "CDS"]);

type ViewType = "LTP" | "OI" | "GREEKS";

/** Raw option row from OpenAlgo optionchain API */
interface RawOptionRow {
  strike_price?: number;
  strike?: number;
  ltp?: number;
  last_price?: number;
  change_percent?: number;
  change_pct?: number;
  oi?: number;
  open_interest?: number;
  oi_change?: number;
  delta?: number;
  gamma?: number;
  theta?: number;
  vega?: number;
  iv?: number;
  implied_volatility?: number;
}

/** OpenAlgo v2 chain entry: { strike, ce: {...}, pe: {...} } */
interface ChainEntry {
  strike: number;
  ce: RawOptionRow | null;
  pe: RawOptionRow | null;
}

/** OpenAlgo optionchain raw API shape (v2 format) */
interface RawOptionChain {
  chain?: ChainEntry[];
  atm_strike?: number;
  underlying_ltp?: number;
  underlying_prev_close?: number;
  pcr?: number;
  // Legacy v1 format (kept for backwards compat)
  calls?: RawOptionRow[];
  puts?: RawOptionRow[];
}

interface StrikeRow {
  strike: number;
  call: RawOptionRow | null;
  put: RawOptionRow | null;
}

interface OrderToast {
  text: string;
  ok: boolean;
}

interface OrderParams {
  symbol: string;
  exchange: string;
  strike: number;
  optionType: string;
  expiry: string;
  action: string;
  ltp: number | null;
}

/** OI interpretation badge type — from OiPulse patterns */
type OISignal =
  | "Long Build Up"   // price up + OI up   → bullish
  | "Short Covering"  // price up + OI down  → short squeeze
  | "Long Unwinding"  // price down + OI down → bulls exiting
  | "Short Build Up"  // price down + OI up  → bearish
  | null;

interface BasketItem {
  strike: number;
  optionType: "CE" | "PE";
  ltp: number | null;
  expiry: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SYMBOLS: SymbolDef[] = [
  // NSE Index Options (NFO)
  { label: "NIFTY",       exchange: "NFO", spotSymbol: "NIFTY",       spotExchange: "NSE_INDEX" },
  { label: "BANKNIFTY",   exchange: "NFO", spotSymbol: "BANKNIFTY",   spotExchange: "NSE_INDEX" },
  { label: "FINNIFTY",    exchange: "NFO", spotSymbol: "FINNIFTY",    spotExchange: "NSE_INDEX" },
  { label: "MIDCPNIFTY",  exchange: "NFO", spotSymbol: "MIDCPNIFTY",  spotExchange: "NSE_INDEX" },
  { label: "NIFTYNXT50",  exchange: "NFO", spotSymbol: "NIFTYNXT50",  spotExchange: "NSE_INDEX" },
  // BSE Index Options (BFO)
  { label: "SENSEX",      exchange: "BFO", spotSymbol: "SENSEX",      spotExchange: "BSE_INDEX" },
  { label: "BANKEX",      exchange: "BFO", spotSymbol: "BANKEX",      spotExchange: "BSE_INDEX" },
  // MCX Commodity Options
  { label: "GOLD",        exchange: "MCX", spotSymbol: "GOLD",        spotExchange: "MCX" },
  { label: "SILVER",      exchange: "MCX", spotSymbol: "SILVER",      spotExchange: "MCX" },
  { label: "CRUDEOIL",    exchange: "MCX", spotSymbol: "CRUDEOIL",    spotExchange: "MCX" },
  { label: "NATURALGAS",  exchange: "MCX", spotSymbol: "NATURALGAS",  spotExchange: "MCX" },
  { label: "COPPER",      exchange: "MCX", spotSymbol: "COPPER",      spotExchange: "MCX" },
  // Currency Options (CDS)
  { label: "USDINR",      exchange: "CDS", spotSymbol: "USDINR",      spotExchange: "CDS" },
  { label: "EURINR",      exchange: "CDS", spotSymbol: "EURINR",      spotExchange: "CDS" },
  { label: "GBPINR",      exchange: "CDS", spotSymbol: "GBPINR",      spotExchange: "CDS" },
  { label: "JPYINR",      exchange: "CDS", spotSymbol: "JPYINR",      spotExchange: "CDS" },
];

const EXCHANGES = ["NFO", "BFO", "MCX", "CDS"];
const VIEWS: ViewType[] = ["LTP", "OI", "GREEKS"];
const STRIKES_AROUND_ATM = 10;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const NUM  = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
const NUM0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

function fmtLtp(v: number | null | undefined): string {
  if (v == null || v === 0) return "—";
  return NUM.format(v);
}

function fmtOI(v: number | null | undefined): string {
  if (v == null || v === 0) return "—";
  const n = Number(v);
  if (n >= 1_00_00_000) return `${(n / 1_00_00_000).toFixed(1)}Cr`;
  if (n >= 1_00_000)    return `${(n / 1_00_000).toFixed(1)}L`;
  if (n >= 1_000)       return `${(n / 1_000).toFixed(1)}K`;
  return NUM0.format(n);
}

function fmtChg(v: number | null | undefined): string {
  if (v == null) return "—";
  const n = Number(v);
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function fmtDelta(v: number | null | undefined): string {
  if (v == null) return "—";
  return Number(v).toFixed(3);
}

function fmtGreek(v: number | null | undefined): string {
  if (v == null) return "—";
  return Number(v).toFixed(4);
}

function fmtIV(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(Number(v) * 100).toFixed(1)}%`;
}

function fmtExpiry(raw: string): string {
  if (!raw) return raw;
  try {
    const d = new Date(raw);
    if (isNaN(d.getTime())) return raw;
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
  } catch {
    return raw;
  }
}

/**
 * Classify OI signal from OiPulse patterns.
 * price change direction + OI change direction → signal type.
 */
function getOISignal(row: RawOptionRow | null): OISignal {
  if (!row) return null;
  const chgPct = row.change_percent ?? row.change_pct ?? null;
  const oiChg  = row.oi_change ?? null;
  if (chgPct == null || oiChg == null) return null;
  const priceUp = Number(chgPct) >= 0;
  const oiUp    = Number(oiChg) >= 0;
  if (priceUp  && oiUp)   return "Long Build Up";
  if (priceUp  && !oiUp)  return "Short Covering";
  if (!priceUp && !oiUp)  return "Long Unwinding";
  /* !priceUp && oiUp */  return "Short Build Up";
}

/** Tailwind classes for each OI signal type */
function oiSignalStyle(signal: OISignal): string {
  switch (signal) {
    case "Long Build Up":   return "bg-profit/15 text-profit border-profit/30";
    case "Short Covering":  return "bg-warning/15 text-warning border-warning/30";
    case "Long Unwinding":  return "bg-orange-500/15 text-orange-400 border-orange-500/30";
    case "Short Build Up":  return "bg-loss/15 text-loss border-loss/30";
    default:                return "";
  }
}

/** Short label for badge */
function oiSignalShort(signal: OISignal): string {
  switch (signal) {
    case "Long Build Up":  return "LBU";
    case "Short Covering": return "SCov";
    case "Long Unwinding": return "LU";
    case "Short Build Up": return "SBU";
    default:               return "";
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Debounce hook for search input */
function useDebounce(value: string, delay: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);
  return debounced;
}

/** Map exchange from search API to option chain exchange */
function mapToOptionExchange(exchange: string): string {
  if (exchange === "NSE" || exchange === "NFO") return "NFO";
  if (exchange === "BSE" || exchange === "BFO") return "BFO";
  if (exchange === "MCX") return "MCX";
  if (exchange === "CDS") return "CDS";
  return "NFO";
}

/** Map exchange to spot exchange for quotes */
function mapToSpotExchange(exchange: string): string {
  if (exchange === "NFO" || exchange === "NSE") return "NSE";
  if (exchange === "BFO" || exchange === "BSE") return "BSE";
  if (exchange === "MCX") return "MCX";
  if (exchange === "CDS") return "CDS";
  return "NSE";
}

/** Convert an InstrumentRecord to a SymbolDef for the option chain */
function instrumentToSymbolDef(inst: InstrumentRecord): SymbolDef {
  const optExchange = mapToOptionExchange(inst.exchange);
  const spotExchange = mapToSpotExchange(inst.exchange);
  return {
    label: inst.symbol,
    exchange: optExchange,
    spotSymbol: inst.symbol,
    spotExchange,
  };
}

/** Searchable symbol combobox — Popover + Command (cmdk) */
function SymbolSearchCombobox({
  activeSymbol,
  onSelect,
  instruments,
}: {
  activeSymbol: SymbolDef;
  onSelect: (sym: SymbolDef) => void;
  instruments: InstrumentRecord[];
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SymbolSearchResult[]>([]);
  const [searchFailed, setSearchFailed] = useState(false);
  const [searching, setSearching] = useState(false);
  const debouncedQuery = useDebounce(query, 300);

  // Known labels in the hardcoded SYMBOLS list — used for deduplication
  const hardcodedLabels = useMemo(() => new Set(SYMBOLS.map((s) => s.label)), []);

  // Extra instruments from the API that aren't in the hardcoded list
  const extraInstruments = useMemo(
    () => instruments.filter((inst) => !hardcodedLabels.has(inst.symbol)),
    [instruments, hardcodedLabels],
  );

  // Client-side filter of instruments matching the query (fallback when API search fails/returns nothing)
  const instrumentFallbackResults = useMemo<SymbolSearchResult[]>(() => {
    if (debouncedQuery.length < 2) return [];
    const q = debouncedQuery.toUpperCase();
    return instruments
      .filter((inst) => inst.symbol.includes(q) || inst.name.toUpperCase().includes(q))
      .slice(0, 15)
      .map((inst) => ({ symbol: inst.symbol, exchange: inst.exchange }));
  }, [debouncedQuery, instruments]);

  // Search API when query changes (2+ chars)
  useEffect(() => {
    if (debouncedQuery.length < 2) {
      setSearchResults([]);
      setSearchFailed(false);
      setSearching(false);
      return;
    }
    let cancelled = false;
    setSearching(true);
    setSearchFailed(false);
    (async () => {
      try {
        const raw = await searchSymbol(debouncedQuery.trim());
        if (cancelled) return;
        const list = Array.isArray(raw)
          ? raw
          : ((raw as unknown as { data?: SymbolSearchResult[] })?.data ?? []);
        setSearchResults(list.slice(0, 15));
        setSearchFailed(false);
      } catch {
        if (!cancelled) {
          setSearchResults([]);
          setSearchFailed(true);
        }
      } finally {
        if (!cancelled) setSearching(false);
      }
    })();
    return () => { cancelled = true; };
  }, [debouncedQuery]);

  // Decide which results to show: live API results, or instrument fallback
  const showingFallback = !searching && debouncedQuery.length >= 2 && (searchFailed || searchResults.length === 0) && instrumentFallbackResults.length > 0;
  const displayResults = showingFallback ? instrumentFallbackResults : searchResults;

  // Look up name for a search result from the instruments list
  function instrumentName(symbol: string): string | null {
    const found = instruments.find((i) => i.symbol === symbol);
    return found?.name ?? null;
  }

  function handleSelectPopular(sym: SymbolDef) {
    onSelect(sym);
    setOpen(false);
    setQuery("");
    setSearchResults([]);
  }

  function handleSelectSearch(result: SymbolSearchResult) {
    const optExchange = mapToOptionExchange(result.exchange);
    const spotExchange = mapToSpotExchange(result.exchange);
    onSelect({
      label: result.symbol,
      exchange: optExchange,
      spotSymbol: result.symbol,
      spotExchange,
    });
    setOpen(false);
    setQuery("");
    setSearchResults([]);
  }

  function handleSelectInstrument(inst: InstrumentRecord) {
    onSelect(instrumentToSymbolDef(inst));
    setOpen(false);
    setQuery("");
    setSearchResults([]);
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          className="flex items-center gap-1 px-2 py-1 text-xs font-semibold text-text-primary bg-surface-hover border border-border-default rounded hover:border-accent/50 transition-colors"
          aria-label="Select symbol"
        >
          <Search size={10} className="text-text-muted" />
          {activeSymbol.label}
          <ChevronDown size={10} className={`text-text-muted transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0 bg-surface-card border-border-default" align="start" sideOffset={4}>
        <Command shouldFilter={false} className="bg-surface-card">
          <CommandInput
            placeholder="Search symbol..."
            value={query}
            onValueChange={setQuery}
            className="text-xs"
          />
          <CommandList className="max-h-72">
            {/* Search results — shown when typing */}
            {debouncedQuery.length >= 2 && (
              <CommandGroup heading={
                searching
                  ? "Searching..."
                  : showingFallback
                    ? `Offline matches for "${debouncedQuery}"`
                    : `Results for "${debouncedQuery}"`
              }>
                {searching && (
                  <div className="flex items-center justify-center py-2">
                    <Loader2 size={14} className="animate-spin text-text-muted" />
                  </div>
                )}
                {!searching && displayResults.length === 0 && (
                  <CommandEmpty>No symbols found</CommandEmpty>
                )}
                {!searching && displayResults.map((r) => {
                  const name = instrumentName(r.symbol);
                  return (
                    <CommandItem
                      key={`${r.symbol}-${r.exchange}`}
                      value={`${r.symbol}-${r.exchange}`}
                      onSelect={() => handleSelectSearch(r)}
                      className="text-xs cursor-pointer"
                    >
                      <span className="font-semibold text-text-primary">{r.symbol}</span>
                      {name && (
                        <span className="ml-1.5 text-xxs text-text-muted truncate max-w-28">{name}</span>
                      )}
                      <span className="ml-auto text-xxs text-text-muted shrink-0">{r.exchange}</span>
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            )}

            {/* Popular symbols — shown when no query */}
            {debouncedQuery.length < 2 && (
              <>
                <CommandGroup heading="Popular">
                  {SYMBOLS.map((sym) => (
                    <CommandItem
                      key={`${sym.label}-${sym.exchange}`}
                      value={`${sym.label}-${sym.exchange}`}
                      onSelect={() => handleSelectPopular(sym)}
                      className={`text-xs cursor-pointer ${
                        sym.label === activeSymbol.label ? "bg-accent/10 text-accent" : ""
                      }`}
                    >
                      <span className="font-semibold">{sym.label}</span>
                      <span className="ml-auto text-xxs text-text-muted">{sym.exchange}</span>
                    </CommandItem>
                  ))}
                </CommandGroup>

                {/* Extra instruments loaded from API */}
                {extraInstruments.length > 0 && (
                  <>
                    <CommandSeparator />
                    <CommandGroup heading="All Instruments">
                      {extraInstruments.slice(0, 50).map((inst) => (
                        <CommandItem
                          key={`inst-${inst.symbol}-${inst.exchange}`}
                          value={`inst-${inst.symbol}-${inst.exchange}`}
                          onSelect={() => handleSelectInstrument(inst)}
                          className={`text-xs cursor-pointer ${
                            inst.symbol === activeSymbol.label ? "bg-accent/10 text-accent" : ""
                          }`}
                        >
                          <span className="font-semibold">{inst.symbol}</span>
                          <span className="ml-1.5 text-xxs text-text-muted truncate max-w-28">{inst.name}</span>
                          <span className="ml-auto text-xxs text-text-muted shrink-0">{inst.exchange}</span>
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  </>
                )}
              </>
            )}

            {/* When searching: show Popular shortcut below results */}
            {debouncedQuery.length >= 2 && displayResults.length > 0 && (
              <>
                <CommandSeparator />
                <CommandGroup heading="Popular">
                  {SYMBOLS.slice(0, 5).map((sym) => (
                    <CommandItem
                      key={`pop-${sym.label}-${sym.exchange}`}
                      value={`pop-${sym.label}-${sym.exchange}`}
                      onSelect={() => handleSelectPopular(sym)}
                      className="text-xs cursor-pointer"
                    >
                      <span className="font-semibold">{sym.label}</span>
                      <span className="ml-auto text-xxs text-text-muted">{sym.exchange}</span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

/** Compact exchange selector dropdown */
function ExchangeSelector({
  value,
  onChange,
}: {
  value: string;
  onChange: (val: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onOut(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onOut);
    return () => document.removeEventListener("mousedown", onOut);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-text-primary bg-surface-hover border border-border-default rounded hover:border-accent/50 transition-colors"
      >
        {value}
        <ChevronDown size={10} className={`text-text-muted transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-0.5 z-50 bg-surface-card border border-border-default rounded shadow-lg min-w-full">
          {EXCHANGES.map((opt) => (
            <button
              key={opt}
              onClick={() => { onChange(opt); setOpen(false); }}
              className={`block w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover transition-colors ${
                opt === value ? "text-accent" : "text-text-primary"
              }`}
            >
              {opt}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

interface OptionChainWidgetProps {
  node?: FlexLayoutNode;
}

export default function OptionChainWidget({ node: _node }: OptionChainWidgetProps) {
  const [symDef, setSymDef] = useState<SymbolDef>(SYMBOLS[0]);
  const [exchangeOverride, setExchangeOverride] = useState<string | null>(null);

  // ---------------------------------------------------------------------------
  // Instruments — fetched once (1-hour staleTime), filtered to option exchanges
  // ---------------------------------------------------------------------------
  const { data: rawInstruments } = useQuery({
    queryKey: ["instruments"],
    queryFn: getInstruments,
    staleTime: 60 * 60 * 1000, // 1 hour
    gcTime: 2 * 60 * 60 * 1000,
    retry: 1,
  });

  const optionInstruments = useMemo<InstrumentRecord[]>(() => {
    if (!rawInstruments) return [];
    return rawInstruments.filter((inst) => OPTION_CHAIN_EXCHANGES.has(inst.exchange));
  }, [rawInstruments]);
  const [expiries, setExpiries] = useState<string[]>([]);
  const [selectedExpiry, setSelectedExpiry] = useState<string | null>(null);
  const [view, setView] = useState<ViewType>("LTP");

  const [chain, setChain] = useState<RawOptionChain | null>(null);
  const [spot, setSpot]   = useState<Quote | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const [orderMsg, setOrderMsg] = useState<OrderToast | null>(null);

  // Basket state — selected strikes for multi-leg orders
  const [basket, setBasket] = useState<BasketItem[]>([]);
  const [basketOpen, setBasketOpen] = useState(false);

  const exchange = exchangeOverride ?? symDef.exchange;

  // ---------------------------------------------------------------------------
  // Symbol details — lot size and metadata for the selected symbol
  // ---------------------------------------------------------------------------
  const { data: symbolDetails } = useQuery({
    queryKey: ["symbol", symDef.label, exchange],
    queryFn: () => getSymbol(symDef.label, exchange),
    staleTime: 30 * 60 * 1000, // 30 minutes — lot sizes rarely change intraday
    gcTime: 60 * 60 * 1000,
    retry: 1,
  });

  const gridRef = useRef<DataEditorRef>(null);

  // Track the current symbol key to detect stale fetches
  const symbolKeyRef = useRef(`${symDef.label}:${exchange}`);
  symbolKeyRef.current = `${symDef.label}:${exchange}`;

  // fetch expiries when symbol/exchange changes
  useEffect(() => {
    setExpiries([]);
    setSelectedExpiry(null);
    setChain(null);
    setError(null);

    const currentKey = `${symDef.label}:${exchange}`;
    let cancelled = false;
    (async () => {
      try {
        const data = await getExpiry(symDef.label, exchange);
        if (cancelled || symbolKeyRef.current !== currentKey) return;
        const list = Array.isArray(data) ? data as string[] : ((data as { expiry?: string[] })?.expiry ?? []);
        setExpiries(list);
        if (list.length > 0) setSelectedExpiry(list[0]);
      } catch (e) {
        if (!cancelled) setError(`Failed to load expiries: ${(e as Error).message}`);
      }
    })();

    return () => { cancelled = true; };
  }, [symDef.label, exchange]);

  // fetch chain + spot
  const fetchData = useCallback(async () => {
    if (!selectedExpiry || expiries.length === 0) return;
    if (!expiries.includes(selectedExpiry)) return;

    const currentKey = `${symDef.label}:${exchange}`;
    setLoading(true);
    setError(null);

    try {
      const [chainData, spotData] = await Promise.allSettled([
        getOptionChain(symDef.label, exchange, selectedExpiry),
        getQuotes(symDef.spotSymbol, symDef.spotExchange),
      ]);

      // Bail out if symbol changed while we were fetching
      if (symbolKeyRef.current !== currentKey) return;

      if (chainData.status === "fulfilled") {
        setChain(chainData.value as unknown as RawOptionChain);
        setError(null); // Clear any stale error from a previous fetch
      } else {
        setError(`Chain error: ${(chainData.reason as Error)?.message}`);
      }

      if (spotData.status === "fulfilled") {
        setSpot(spotData.value);
      }
    } finally {
      setLoading(false);
      setLastRefresh(new Date());
    }
  }, [selectedExpiry, symDef, exchange, expiries]);

  // auto-refresh
  useEffect(() => {
    fetchData();
    const interval = isMarketHours() ? 3000 : 30000;
    const id = setInterval(fetchData, interval);
    return () => clearInterval(id);
  }, [fetchData]);

  // scroll ATM into view when chain loads
  useEffect(() => {
    if (atmStrike == null || !gridRef.current) return;
    const atmIdx = strikes.findIndex((s) => s.strike === atmStrike);
    if (atmIdx >= 0) {
      setTimeout(() => {
        gridRef.current?.scrollTo(0, atmIdx, "vertical", 0, 80, { vAlign: "center" });
      }, 100);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chain]);

  // compute ordered strike list, ATM, max OI, computed PCR
  const { strikes, atmStrike, maxCallOI, maxPutOI, computedPCR } = useMemo(() => {
    if (!chain) return {
      strikes: [] as StrikeRow[],
      atmStrike: null as number | null,
      maxCallOI: 0,
      maxPutOI: 0,
      computedPCR: null as number | null,
    };

    const callMap: Record<number, RawOptionRow> = {};
    const putMap:  Record<number, RawOptionRow> = {};

    if (chain.chain && chain.chain.length > 0) {
      // OpenAlgo v2 format: chain[].strike, chain[].ce, chain[].pe
      for (const entry of chain.chain) {
        if (entry.ce) callMap[entry.strike] = { ...entry.ce, strike: entry.strike };
        if (entry.pe) putMap[entry.strike]  = { ...entry.pe, strike: entry.strike };
      }
    } else {
      // Legacy v1 format: separate calls[] and puts[] arrays
      (chain.calls ?? []).forEach((c) => { callMap[c.strike_price ?? c.strike ?? 0] = c; });
      (chain.puts  ?? []).forEach((p) => { putMap[p.strike_price  ?? p.strike  ?? 0] = p; });
    }

    const allStrikes = Array.from(
      new Set([
        ...Object.keys(callMap).map(Number),
        ...Object.keys(putMap).map(Number),
      ])
    ).sort((a, b) => a - b);

    const atm = chain.atm_strike ?? (spot?.ltp
      ? allStrikes.reduce((prev, cur) =>
          Math.abs(cur - spot.ltp) < Math.abs(prev - spot.ltp) ? cur : prev,
          allStrikes[0] ?? 0)
      : allStrikes[Math.floor(allStrikes.length / 2)] ?? null);

    const atmIdx = allStrikes.indexOf(atm ?? 0);
    const lo = Math.max(0, atmIdx - STRIKES_AROUND_ATM);
    const hi = Math.min(allStrikes.length - 1, atmIdx + STRIKES_AROUND_ATM);
    const visible = allStrikes.slice(lo, hi + 1);

    const maxCallOI = Math.max(0, ...visible.map((s) => Number(callMap[s]?.oi ?? callMap[s]?.open_interest ?? 0)));
    const maxPutOI  = Math.max(0, ...visible.map((s) => Number(putMap[s]?.oi  ?? putMap[s]?.open_interest  ?? 0)));

    // Compute PCR from total put OI / total call OI (all visible strikes)
    const totalCallOI = visible.reduce((acc, s) => acc + Number(callMap[s]?.oi ?? callMap[s]?.open_interest ?? 0), 0);
    const totalPutOI  = visible.reduce((acc, s) => acc + Number(putMap[s]?.oi  ?? putMap[s]?.open_interest  ?? 0), 0);
    const computedPCR = totalCallOI > 0 ? totalPutOI / totalCallOI : null;

    return {
      strikes: visible.map((s) => ({ strike: s, call: callMap[s] ?? null, put: putMap[s] ?? null })),
      atmStrike: atm,
      maxCallOI,
      maxPutOI,
      computedPCR,
    };
  }, [chain, spot]);

  // spot derived values
  const spotLtp       = spot?.ltp ?? null;
  const spotPrevClose = (spot as unknown as { prev_close?: number })?.prev_close ?? spot?.close ?? null;
  const spotChange    = spotLtp && spotPrevClose ? spotLtp - spotPrevClose : null;
  const spotChangePct = spotChange && spotPrevClose ? (spotChange / spotPrevClose) * 100 : null;
  const spotUp        = spotChange == null ? null : spotChange >= 0;

  // PCR — prefer API value, fallback to computed
  const pcr = chain?.pcr != null ? chain.pcr : computedPCR;

  // order handler — resolves the exact trading symbol via getOptionSymbol before placing the order.
  // The offset parameter accepts "ATM", "ATM+N", "ATM-N", or the literal strike price as a string.
  // Here we know the exact strike, so we pass it directly as the offset value.
  async function handleOrder({ strike, optionType, expiry, action }: OrderParams) {
    let orderSymbol = `${symDef.label}${expiry}${strike}${optionType}`;
    let orderExchange = exchange;
    try {
      // Resolve the canonical broker trading symbol from OpenAlgo.
      // getOptionSymbol(underlying, exchange, expiry_date, option_type, offset)
      // offset = strike price as string when we know the exact strike.
      const resolved = await getOptionSymbol(
        symDef.label,
        exchange,
        expiry,
        optionType,
        String(strike),
      );
      orderSymbol = resolved.symbol;
      orderExchange = resolved.exchange;
    } catch {
      // If symbol resolution fails, fall back to the manually constructed symbol.
      // This keeps existing behavior intact for brokers where optionsymbol is not required.
    }
    try {
      await placeOrder({
        strategy: "FlintChain",
        symbol: orderSymbol,
        exchange: orderExchange,
        action: action === "B" ? "BUY" : "SELL",
        quantity: 1,
        orderType: "MARKET",
        product: "MIS",
      });
      setOrderMsg({ text: `${action} ${orderSymbol} sent`, ok: true });
    } catch (e) {
      setOrderMsg({ text: (e as Error).message, ok: false });
    } finally {
      setTimeout(() => setOrderMsg(null), 3000);
    }
  }

  // basket helpers
  function addToBasket(strike: number, optionType: "CE" | "PE", ltp: number | null) {
    if (!selectedExpiry) return;
    setBasket((prev) => {
      const exists = prev.some((b) => b.strike === strike && b.optionType === optionType);
      if (exists) return prev;
      return [...prev, { strike, optionType, ltp, expiry: selectedExpiry }];
    });
    setBasketOpen(true);
  }

  function removeFromBasket(strike: number, optionType: "CE" | "PE") {
    setBasket((prev) => prev.filter((b) => !(b.strike === strike && b.optionType === optionType)));
  }

  function isInBasket(strike: number, optionType: "CE" | "PE"): boolean {
    return basket.some((b) => b.strike === strike && b.optionType === optionType);
  }

  // Synthetic future — only for equity/index options (not MCX/CDS)
  const showSyntheticFuture = exchange === "NFO" || exchange === "BFO";
  const { data: syntheticFutureData } = useSyntheticFuture(
    symDef.label,
    exchange,
    selectedExpiry ?? undefined,
  );

  const expiryButtons = expiries.slice(0, 5);

  // ---------------------------------------------------------------------------
  // Glide Data Grid — theme, columns, getCellContent
  // ---------------------------------------------------------------------------

  const glideTheme: Partial<Theme> = useMemo(() => ({
    // Surface tokens (raw hex — Glide needs literal values)
    bgCell: "#0a0a0f",           // surface-base
    bgCellMedium: "#16161f",     // surface-card
    bgHeader: "#16161f",         // surface-card
    bgHeaderHasFocus: "#24242e", // surface-hover
    bgHeaderHovered: "#24242e",  // surface-hover
    // Text tokens
    textDark: "#e4e4e7",         // text-primary
    textMedium: "#8b8b95",       // text-secondary
    textLight: "#6b6b78",        // text-muted
    textHeader: "#8b8b95",       // text-secondary
    // Accent
    accentColor: "#6366f1",
    accentFg: "#ffffff",
    // Border token
    borderColor: "#2a2a3a",      // border-default
    // Typography
    fontFamily: "JetBrains Mono, monospace",
    baseFontStyle: "11px",
    headerFontStyle: "500 10px",
    editorFontSize: "11px",
  }), []);

  // Column definitions — vary by active view
  const glideColumns: GridColumn[] = useMemo(() => {
    if (view === "LTP") {
      return [
        { title: "SIG",  width: 38, id: "c_sig"  },
        { title: "CHG%", width: 52, id: "c_chg"  },
        { title: "LTP",  width: 60, id: "c_ltp"  },
        { title: "OI",   width: 54, id: "c_oi"   },
        { title: "CALL", width: 52, id: "c_act"  },
        { title: "STRIKE", width: 58, id: "strike" },
        { title: "PUT",  width: 52, id: "p_act"  },
        { title: "LTP",  width: 60, id: "p_ltp"  },
        { title: "CHG%", width: 52, id: "p_chg"  },
        { title: "OI",   width: 54, id: "p_oi"   },
        { title: "SIG",  width: 38, id: "p_sig"  },
      ];
    }
    if (view === "OI") {
      return [
        { title: "SIG",    width: 38, id: "c_sig"    },
        { title: "OI CHG", width: 58, id: "c_oichg"  },
        { title: "OI",     width: 54, id: "c_oi"     },
        { title: "LTP",    width: 60, id: "c_ltp"    },
        { title: "CALL",   width: 52, id: "c_act"    },
        { title: "STRIKE", width: 58, id: "strike"   },
        { title: "PUT",    width: 52, id: "p_act"    },
        { title: "LTP",    width: 60, id: "p_ltp"    },
        { title: "OI",     width: 54, id: "p_oi"     },
        { title: "OI CHG", width: 58, id: "p_oichg"  },
        { title: "SIG",    width: 38, id: "p_sig"    },
      ];
    }
    // GREEKS
    return [
      { title: "IV",    width: 50, id: "c_iv"    },
      { title: "DELTA", width: 52, id: "c_delta" },
      { title: "GAMMA", width: 52, id: "c_gamma" },
      { title: "THETA", width: 52, id: "c_theta" },
      { title: "VEGA",  width: 52, id: "c_vega"  },
      { title: "CALL",  width: 52, id: "c_act"   },
      { title: "STRIKE", width: 58, id: "strike" },
      { title: "PUT",   width: 52, id: "p_act"   },
      { title: "DELTA", width: 52, id: "p_delta" },
      { title: "GAMMA", width: 52, id: "p_gamma" },
      { title: "THETA", width: 52, id: "p_theta" },
      { title: "VEGA",  width: 52, id: "p_vega"  },
      { title: "IV",    width: 50, id: "p_iv"    },
    ];
  }, [view]);

  /** Build OI bar text representation: e.g. "████ 12.4L" */
  function oiBarText(value: number | null | undefined, maxValue: number): string {
    if (!value || !maxValue) return "";
    const pct = Math.min((Number(value) / Number(maxValue)) * 100, 100);
    const bars = Math.round(pct / 20); // 0-5 blocks
    return "█".repeat(bars) + " " + fmtOI(value);
  }

  /** OI signal short text */
  function oiSigText(signal: OISignal): string {
    return signal ? oiSignalShort(signal) : "—";
  }

  /**
   * Returns a text colour for positive/negative numbers.
   * Glide accepts CSS colour strings as themeOverride on individual cells.
   */
  function chgColour(v: number | null | undefined): string | undefined {
    if (v == null) return undefined;
    return Number(v) >= 0 ? "#4ade80" : "#f87171";
  }

  function mkText(
    display: string,
    opts?: { themeOverride?: Partial<Theme>; readonly?: boolean },
  ): GridCell {
    return {
      kind: GridCellKind.Text,
      data: display,
      displayData: display,
      allowOverlay: false,
      themeOverride: opts?.themeOverride,
      readonly: true,
    };
  }

  /**
   * Action cell — shows "+B" text; clicking toggles basket membership for this strike.
   * The basket panel handles the actual order placement.
   */
  function mkAction(label: "B/S CE" | "B/S PE", inBasket: boolean): GridCell {
    return {
      kind: GridCellKind.Text,
      data: label,
      displayData: inBasket ? "✓ B" : "+B",
      allowOverlay: false,
      themeOverride: inBasket
        ? { textDark: "#818cf8", baseFontStyle: "bold 10px" }
        : { textDark: "#6366f1", baseFontStyle: "600 10px" },
      readonly: true,
    };
  }

  const getCellContent = useCallback(([col, row]: Item): GridCell => {
    const strikeRow = strikes[row];
    if (!strikeRow) return mkText("—");

    const { strike, call, put } = strikeRow;
    const colId = glideColumns[col]?.id ?? "";

    if (colId === "strike") {
      const isAtm = strike === atmStrike;
      return {
        kind: GridCellKind.Text,
        data: NUM0.format(strike),
        displayData: isAtm ? `▶ ${NUM0.format(strike)}` : NUM0.format(strike),
        allowOverlay: false,
        themeOverride: isAtm
          ? { textDark: "#eab308", baseFontStyle: "bold 11px" }  // ATM gold/amber
          : undefined,
        readonly: true,
      };
    }

    // ------ LTP view ------
    const ceInBasket = isInBasket(strike, "CE");
    const peInBasket = isInBasket(strike, "PE");

    if (view === "LTP") {
      const cLtp   = call?.ltp ?? call?.last_price ?? null;
      const cChg   = call?.change_percent ?? call?.change_pct ?? null;
      const cOI    = call?.oi ?? call?.open_interest ?? null;
      const cSig   = getOISignal(call);
      const pLtp   = put?.ltp ?? put?.last_price ?? null;
      const pChg   = put?.change_percent ?? put?.change_pct ?? null;
      const pOI    = put?.oi ?? put?.open_interest ?? null;
      const pSig   = getOISignal(put);

      switch (colId) {
        case "c_sig":  return mkText(oiSigText(cSig));
        case "c_chg":  return mkText(fmtChg(cChg), { themeOverride: { textDark: chgColour(cChg) ?? "#a0a0b0" } });
        case "c_ltp":  return mkText(fmtLtp(cLtp));
        case "c_oi":   return mkText(oiBarText(cOI, maxCallOI));
        case "c_act":  return mkAction("B/S CE", ceInBasket);
        case "p_act":  return mkAction("B/S PE", peInBasket);
        case "p_ltp":  return mkText(fmtLtp(pLtp));
        case "p_chg":  return mkText(fmtChg(pChg), { themeOverride: { textDark: chgColour(pChg) ?? "#a0a0b0" } });
        case "p_oi":   return mkText(oiBarText(pOI, maxPutOI));
        case "p_sig":  return mkText(oiSigText(pSig));
      }
    }

    // ------ OI view ------
    if (view === "OI") {
      const cLtp    = call?.ltp ?? call?.last_price ?? null;
      const cOI     = call?.oi ?? call?.open_interest ?? null;
      const cOiChg  = call?.oi_change ?? null;
      const cSig    = getOISignal(call);
      const pLtp    = put?.ltp ?? put?.last_price ?? null;
      const pOI     = put?.oi ?? put?.open_interest ?? null;
      const pOiChg  = put?.oi_change ?? null;
      const pSig    = getOISignal(put);

      const fmtOiChg = (v: number | null) =>
        v != null ? `${Number(v) >= 0 ? "+" : ""}${fmtOI(Math.abs(v))}` : "—";

      switch (colId) {
        case "c_sig":   return mkText(oiSigText(cSig));
        case "c_oichg": return mkText(fmtOiChg(cOiChg), { themeOverride: { textDark: chgColour(cOiChg) ?? "#a0a0b0" } });
        case "c_oi":    return mkText(fmtOI(cOI));
        case "c_ltp":   return mkText(fmtLtp(cLtp));
        case "c_act":   return mkAction("B/S CE", ceInBasket);
        case "p_act":   return mkAction("B/S PE", peInBasket);
        case "p_ltp":   return mkText(fmtLtp(pLtp));
        case "p_oi":    return mkText(fmtOI(pOI));
        case "p_oichg": return mkText(fmtOiChg(pOiChg), { themeOverride: { textDark: chgColour(pOiChg) ?? "#a0a0b0" } });
        case "p_sig":   return mkText(oiSigText(pSig));
      }
    }

    // ------ GREEKS view ------
    {
      const cIV     = call?.iv ?? call?.implied_volatility ?? null;
      const cDelta  = call?.delta ?? null;
      const cGamma  = call?.gamma ?? null;
      const cTheta  = call?.theta ?? null;
      const cVega   = call?.vega ?? null;
      const pIV     = put?.iv ?? put?.implied_volatility ?? null;
      const pDelta  = put?.delta ?? null;
      const pGamma  = put?.gamma ?? null;
      const pTheta  = put?.theta ?? null;
      const pVega   = put?.vega ?? null;

      switch (colId) {
        case "c_iv":    return mkText(fmtIV(cIV));
        case "c_delta": return mkText(fmtDelta(cDelta));
        case "c_gamma": return mkText(fmtGreek(cGamma));
        case "c_theta": return mkText(fmtGreek(cTheta));
        case "c_vega":  return mkText(fmtGreek(cVega));
        case "c_act":   return mkAction("B/S CE", ceInBasket);
        case "p_act":   return mkAction("B/S PE", peInBasket);
        case "p_delta": return mkText(fmtDelta(pDelta));
        case "p_gamma": return mkText(fmtGreek(pGamma));
        case "p_theta": return mkText(fmtGreek(pTheta));
        case "p_vega":  return mkText(fmtGreek(pVega));
        case "p_iv":    return mkText(fmtIV(pIV));
      }
    }

    return mkText("—");
  }, [strikes, atmStrike, view, glideColumns, maxCallOI, maxPutOI, isInBasket]);

  /**
   * Handle clicks on action columns.
   * Single-click adds the strike to the basket (opens basket panel).
   * The basket panel then allows multi-leg order placement.
   * This approach is used because canvas cells cannot host React sub-components.
   */
  const handleCellClicked = useCallback(([col, row]: Item) => {
    const colId = glideColumns[col]?.id ?? "";
    if (colId !== "c_act" && colId !== "p_act") return;
    const strikeRow = strikes[row];
    if (!strikeRow) return;
    const { strike, call, put } = strikeRow;
    const isCE = colId === "c_act";
    const ltp = isCE
      ? (call?.ltp ?? call?.last_price ?? null)
      : (put?.ltp  ?? put?.last_price  ?? null);
    if (isInBasket(strike, isCE ? "CE" : "PE")) {
      removeFromBasket(strike, isCE ? "CE" : "PE");
    } else {
      addToBasket(strike, isCE ? "CE" : "PE", ltp);
    }
  }, [glideColumns, strikes, isInBasket, addToBasket, removeFromBasket]);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden select-none">

      {/* Top bar */}
      <div className="flex-none bg-surface-card border-b border-border-default px-2 py-1.5 space-y-1.5">

        {/* Row 1: Symbol + Exchange + Expiry + View + Basket + Refresh — all in one line */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <SymbolSearchCombobox
            activeSymbol={symDef}
            onSelect={(newSym) => {
              setSymDef(newSym);
              setExchangeOverride(null);
            }}
            instruments={optionInstruments}
          />

          <ExchangeSelector
            value={exchange}
            onChange={setExchangeOverride}
          />

          <div className="flex items-center gap-1">
            {expiryButtons.length === 0 && !loading && (
              <span className="text-xs text-text-muted px-1">No expiries</span>
            )}
            {expiryButtons.map((exp) => (
              <button
                key={exp}
                onClick={() => setSelectedExpiry(exp)}
                className={`px-2 py-0.5 text-xs font-medium rounded border transition-colors ${
                  exp === selectedExpiry
                    ? "bg-accent/15 border-accent/60 text-accent"
                    : "bg-surface-hover border-border-default text-text-secondary hover:text-text-primary hover:border-accent/30"
                }`}
              >
                {fmtExpiry(exp)}
              </button>
            ))}
          </div>

          <div className="flex-1" />

          {/* View toggle */}
          <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
            {VIEWS.map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={`px-2 py-0.5 text-xs font-medium transition-colors ${
                  v === view
                    ? "bg-accent/15 text-accent"
                    : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
                }`}
              >
                {v}
              </button>
            ))}
          </div>

          {/* Basket button */}
          <button
            onClick={() => setBasketOpen((p) => !p)}
            className={`relative flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded border transition-colors ${
              basketOpen
                ? "bg-accent/15 border-accent/50 text-accent"
                : "bg-surface-hover border-border-default text-text-muted hover:text-text-primary hover:border-accent/30"
            }`}
            title="Basket orders"
          >
            <ShoppingBasket size={11} />
            {basket.length > 0 && (
              <span className="absolute -top-1 -right-1 flex items-center justify-center w-3.5 h-3.5 text-xxs font-bold rounded-full bg-accent text-white leading-none">
                {basket.length}
              </span>
            )}
          </button>

          <button
            onClick={fetchData}
            disabled={loading}
            className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors disabled:opacity-40"
            title="Refresh"
          >
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          </button>
        </div>

        {/* Row 2: spot LTP with change% + PCR badge */}
        <div className="flex items-center gap-3 flex-wrap">
          {spotLtp != null ? (
            <>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-text-muted uppercase tracking-wide">Spot</span>
                <span className="font-mono text-sm font-bold text-text-primary">
                  {NUM.format(spotLtp)}
                </span>
                {spotChange != null && (
                  <div className={`flex items-center gap-0.5 text-xs font-mono font-semibold ${spotUp ? "text-profit" : "text-loss"}`}>
                    {spotUp
                      ? <TrendingUp size={12} strokeWidth={2.5} />
                      : <TrendingDown size={12} strokeWidth={2.5} />
                    }
                    <span>{spotChange >= 0 ? "+" : ""}{spotChange.toFixed(2)}</span>
                    <span className="text-xs opacity-80">
                      ({spotChangePct != null && spotChangePct >= 0 ? "+" : ""}{spotChangePct?.toFixed(2)}%)
                    </span>
                  </div>
                )}
              </div>
            </>
          ) : (
            <span className="text-xs text-text-muted">Spot: —</span>
          )}

          {/* Lot size badge — populated by getSymbol query */}
          {symbolDetails?.lotsize != null && symbolDetails.lotsize > 0 && (
            <div className="flex items-center gap-1 px-2 py-0.5 rounded border bg-surface-card border-border-default text-xs font-mono">
              <span className="text-text-muted font-sans">Lot</span>
              <span className="font-semibold text-text-primary">{NUM0.format(symbolDetails.lotsize)}</span>
            </div>
          )}

          {/* Synthetic future price badge */}
          {showSyntheticFuture && syntheticFutureData?.synthetic_future_price != null && (
            <div className="flex flex-col gap-0 px-2 py-0.5 rounded border bg-surface-card border-border-default">
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-text-secondary uppercase tracking-wide">Syn Future</span>
                <span className="font-mono text-sm font-bold text-text-primary">
                  ₹{syntheticFutureData.synthetic_future_price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
                </span>
              </div>
              {syntheticFutureData.atm_strike != null && (
                <span className="text-xxs text-text-muted font-mono">
                  ATM {NUM0.format(syntheticFutureData.atm_strike)}
                </span>
              )}
            </div>
          )}

          {/* PCR badge — bullish/bearish/neutral token colors */}
          {pcr != null && (
            <div className={`flex items-center gap-1 px-2 py-0.5 rounded border text-xs font-semibold font-mono ${
              Number(pcr) >= 1.2
                ? "bg-bullish-bg border-bullish-border text-bullish-text"
                : Number(pcr) <= 0.8
                  ? "bg-bearish-bg border-bearish-border text-bearish-text"
                  : "bg-atm-bg border-atm-border text-atm-text"
            }`}>
              <span className="font-sans font-medium text-text-muted mr-0.5">PCR</span>
              {Number(pcr).toFixed(2)}
              <span className="ml-1 font-sans font-normal text-xxs opacity-70">
                {Number(pcr) >= 1.2 ? "Bullish" : Number(pcr) <= 0.8 ? "Bearish" : "Neutral"}
              </span>
            </div>
          )}

          {lastRefresh && (
            <div className="flex items-center gap-1 ml-auto text-xs text-text-muted">
              <RefreshCw size={9} />
              {lastRefresh.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}
            </div>
          )}
        </div>

        {/* OI signal legend (compact, shown only in OI/LTP view) */}
        {view !== "GREEKS" && (
          <div className="flex items-center gap-2 flex-wrap">
            {(["Long Build Up", "Short Covering", "Long Unwinding", "Short Build Up"] as OISignal[]).map((sig) => (
              <span
                key={sig}
                className={`inline-flex items-center gap-1 px-1 py-0 text-xxs font-medium rounded border ${oiSignalStyle(sig)}`}
              >
                <span className="font-bold">{oiSignalShort(sig)}</span>
                <span className="opacity-70">{sig}</span>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Error banner */}
      {error && (
        <div className="flex-none flex items-center gap-2 px-2 py-1 bg-loss/10 border-b border-loss/20 text-loss text-xs">
          <AlertCircle size={11} />
          <span>{error}</span>
        </div>
      )}

      {/* Order toast */}
      {orderMsg && (
        <div className={`flex-none px-2 py-1 text-xs border-b ${
          orderMsg.ok
            ? "bg-profit/10 border-profit/20 text-profit"
            : "bg-loss/10 border-loss/20 text-loss"
        }`}>
          {orderMsg.text}
        </div>
      )}

      {/* Basket panel */}
      {basketOpen && (
        <div className="flex-none bg-surface-card border-b border-border-default px-2 py-1.5">
          <div className="flex items-center gap-2 mb-1">
            <ShoppingBasket size={11} className="text-accent" />
            <span className="text-xs font-semibold text-text-primary uppercase tracking-wide">
              Basket ({basket.length})
            </span>
            {basket.length > 0 && (
              <button
                onClick={() => setBasket([])}
                className="ml-auto text-xxs text-text-muted hover:text-loss transition-colors"
              >
                Clear all
              </button>
            )}
          </div>
          {basket.length === 0 ? (
            <p className="text-xs text-text-muted">
              Click +B on any strike to add it here.
            </p>
          ) : (
            <>
              <div className="flex flex-wrap gap-1 mb-1.5">
                {basket.map((item) => (
                  <div
                    key={`${item.strike}-${item.optionType}`}
                    className={`flex items-center gap-1 px-1.5 py-0.5 rounded border text-xs font-mono ${
                      item.optionType === "CE"
                        ? "bg-loss/10 border-loss/30 text-loss"
                        : "bg-profit/10 border-profit/30 text-profit"
                    }`}
                  >
                    <span className="font-semibold">{NUM0.format(item.strike)} {item.optionType}</span>
                    {item.ltp != null && (
                      <span className="text-text-muted">@ {fmtLtp(item.ltp)}</span>
                    )}
                    <button
                      onClick={() => removeFromBasket(item.strike, item.optionType)}
                      className="ml-0.5 text-text-muted hover:text-text-primary transition-colors"
                      aria-label="Remove"
                    >
                      <X size={9} />
                    </button>
                  </div>
                ))}
              </div>
              <div className="flex gap-1.5 pt-1 border-t border-border-default">
                <button
                  onClick={() =>
                    basket.forEach((item) =>
                      handleOrder({ symbol: symDef.label, exchange, strike: item.strike, optionType: item.optionType, expiry: item.expiry, action: "B", ltp: item.ltp })
                    )
                  }
                  className="px-3 py-0.5 text-xs font-semibold rounded bg-profit/10 text-profit hover:bg-profit/20 border border-profit/30 hover:border-profit/60 transition-colors"
                >
                  Buy All
                </button>
                <button
                  onClick={() =>
                    basket.forEach((item) =>
                      handleOrder({ symbol: symDef.label, exchange, strike: item.strike, optionType: item.optionType, expiry: item.expiry, action: "S", ltp: item.ltp })
                    )
                  }
                  className="px-3 py-0.5 text-xs font-semibold rounded bg-loss/10 text-loss hover:bg-loss/20 border border-loss/30 hover:border-loss/60 transition-colors"
                >
                  Sell All
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* Chain table — Glide Data Grid (canvas-rendered, high-performance) */}
      <div className="flex-1 min-h-0">
        {!selectedExpiry && !loading ? (
          <div className="h-full flex items-center justify-center text-text-muted text-xs">
            Select an expiry to load chain
          </div>
        ) : loading && !chain ? (
          <div className="h-full flex items-center justify-center text-text-muted text-xs gap-2">
            <RefreshCw size={13} className="animate-spin" />
            Loading chain…
          </div>
        ) : strikes.length === 0 ? (
          <div className="h-full flex items-center justify-center text-text-muted text-xs">
            No strike data
          </div>
        ) : (
          <DataEditor
            ref={gridRef}
            columns={glideColumns}
            rows={strikes.length}
            getCellContent={getCellContent}
            onCellClicked={handleCellClicked}
            theme={glideTheme}
            rowHeight={24}
            headerHeight={26}
            smoothScrollX
            smoothScrollY
            rangeSelect="none"
            columnSelect="none"
            rowSelect="none"
            getCellsForSelection
            width="100%"
            height="100%"
            {...({
              getRowThemeOverride: (row: number) => {
                const s = strikes[row];
                if (!s) return undefined;
                // ATM row: gold/amber tint background
                return s.strike === atmStrike
                  ? { bgCell: "#eab30812", bgCellMedium: "#eab30818" }
                  : undefined;
              },
            } as object)}
          />
        )}
      </div>

      {/* Footer */}
      {chain && strikes.length > 0 && (
        <div className="flex-none bg-surface-card border-t border-border-default px-3 py-1 flex items-center gap-4 text-xs">
          <span className="text-text-muted uppercase tracking-wide font-medium">Total OI</span>
          <span className="text-loss font-mono font-semibold">
            CE: {fmtOI(strikes.reduce((s, r) => s + Number(r.call?.oi ?? r.call?.open_interest ?? 0), 0))}
          </span>
          <span className="text-profit font-mono font-semibold">
            PE: {fmtOI(strikes.reduce((s, r) => s + Number(r.put?.oi  ?? r.put?.open_interest  ?? 0), 0))}
          </span>
          {atmStrike != null && (
            <span className="text-text-muted">
              ATM: <span className="font-mono text-atm-text font-semibold">{NUM0.format(atmStrike)}</span>
            </span>
          )}
          {basket.length > 0 && (
            <span className="text-accent font-semibold">
              Basket: {basket.length} leg{basket.length > 1 ? "s" : ""}
            </span>
          )}
          <span className="ml-auto text-text-muted flex items-center gap-1.5">
            <span className={`inline-block w-1.5 h-1.5 rounded-full ${isMarketHours() ? "bg-profit" : "bg-text-muted"}`} />
            {isMarketHours() ? "Live" : "Closed"} · {isMarketHours() ? "3s" : "30s"}
          </span>
        </div>
      )}
    </div>
  );
}
