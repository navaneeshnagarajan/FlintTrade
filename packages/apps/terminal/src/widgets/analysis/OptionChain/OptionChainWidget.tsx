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
 *   - Flash animation on LTP change: green flash (price up), red flash (price down) — 500ms
 *   - Max Pain badge in header (fetched from OpenAlgo max_pain endpoint)
 *   - Auto-refresh: 3 s market hours, 30 s off-hours
 *   - Dense layout: text-xs data, text-xs headers, font-mono numbers
 *   - Glide theme uses design token hex values (surface/border/text tokens)
 */

import { useState, useEffect, useCallback, useRef, useMemo, useReducer, memo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSyntheticFuture } from "@/hooks/useSyntheticFuture";
import DataEditor, {
  type DataEditorRef,
  type Item,
} from "@glideapps/glide-data-grid";
import "@glideapps/glide-data-grid/dist/index.css";
import {
  RefreshCw,
  TrendingUp,
  TrendingDown,
  AlertCircle,
  ShoppingBasket,
  Layers,
} from "lucide-react";
import { getInstruments, getOptionSymbol, getSymbol, placeOrder, getMaxPain } from "@/services/api";
import { isMarketHours } from "@/lib/market";
import { useOptionChainData } from "./useOptionChainData";
import SymbolSearch from "./SymbolSearch";
import BasketPanel from "./BasketPanel";
import LegBuilder, { type LegBuilderHandle } from "./LegBuilder";
import { getColumns, buildGetCellContent, ATM_ROW_THEME } from "./gridConfig";
import { useGlideTheme } from "@/hooks/useGlideTheme";
import { NUM, NUM0, fmtExpiry, fmtOI, oiSignalStyle, oiSignalShort } from "./formatters";
import ExchangeSelector from "./ExchangeSelector";
import type {
  SymbolDef,
  ViewType,
  OrderToast,
  OrderParams,
  BasketItem,
  OISignal,
  InstrumentRecord,
} from "./types";
import { SYMBOLS, VIEWS, OPTION_CHAIN_EXCHANGES } from "./types";
import type { IDockviewPanelProps } from "dockview-react";

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function OptionChainWidget(props: Partial<IDockviewPanelProps> = {}) {
  const glideTheme = useGlideTheme();
  // Honour a pinned symbol from the Dockview panel params (e.g. the options-
  // scalper preset pins `{ symbol: "NIFTY" }`). Falls back to the first known
  // underlying. Previously the widget ignored params and only worked for the
  // default by coincidence.
  const pinnedSymbol = (props.params as { symbol?: string } | undefined)?.symbol;
  const initialSymDef = SYMBOLS.find((s) => s.label === pinnedSymbol) ?? SYMBOLS[0];
  const [symDef, setSymDef]                     = useState<SymbolDef>(initialSymDef);
  const [exchangeOverride, setExchangeOverride] = useState<string | null>(null);
  const [view, setView]                         = useState<ViewType>("LTP");
  const [basket, setBasket]                     = useState<BasketItem[]>([]);
  const [basketOpen, setBasketOpen]             = useState(false);
  const [legBuilderOpen, setLegBuilderOpen]     = useState(false);
  const legBuilderRef                           = useRef<LegBuilderHandle>(null);
  const [orderMsg, setOrderMsg]                 = useState<OrderToast | null>(null);
  const [secondsAgo, setSecondsAgo]             = useState<number | null>(null);
  const orderMsgTimerRef                        = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const scrollTimerRef                          = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const gridRef                                 = useRef<DataEditorRef>(null);

  // Flash animation tracking: Map<"strikeIndex_CE|PE", "up"|"down"> cleared after 500ms
  const flashStateRef = useRef<Map<string, "up" | "down">>(new Map());
  const flashTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const prevLtpRef = useRef<Map<string, number>>(new Map());
  // Counter bumped to force getCellContent re-evaluation when flash state changes
  const [flashTick, bumpFlashTick] = useReducer((n: number) => n + 1, 0);

  useEffect(() => () => {
    clearTimeout(orderMsgTimerRef.current);
    clearTimeout(scrollTimerRef.current);
    flashTimersRef.current.forEach(clearTimeout);
    flashTimersRef.current.clear();
  }, []);

  const exchange = exchangeOverride ?? symDef.exchange;

  // Instruments — fetched once per hour, filtered to option exchanges
  const { data: rawInstruments } = useQuery({
    queryKey: ["instruments"],
    queryFn: getInstruments,
    staleTime: 60 * 60 * 1000,
    gcTime: 2 * 60 * 60 * 1000,
    retry: 1,
  });

  const optionInstruments = useMemo<InstrumentRecord[]>(() => {
    if (!rawInstruments) return [];
    return rawInstruments.filter((inst) => OPTION_CHAIN_EXCHANGES.has(inst.exchange));
  }, [rawInstruments]);

  // Symbol details — lot size
  const { data: symbolDetails } = useQuery({
    queryKey: ["symbol", symDef.label, exchange],
    queryFn: () => getSymbol(symDef.label, exchange),
    staleTime: 30 * 60 * 1000,
    gcTime: 60 * 60 * 1000,
    retry: 1,
  });

  // Data hook — expiries, chain, spot, derived values
  const {
    expiries,
    selectedExpiry,
    setSelectedExpiry,
    chain,
    loading,
    error,
    lastRefresh,
    fetchData,
    strikes,
    atmStrike,
    maxCallOI,
    maxPutOI,
    spotLtp,
    spotChange,
    spotChangePct,
    spotUp,
    pcr,
  } = useOptionChainData(symDef, exchange);

  // Clear stale LTP references when symbol or expiry changes to prevent false flash animations
  useEffect(() => {
    prevLtpRef.current.clear();
    flashStateRef.current.clear();
    flashTimersRef.current.forEach(clearTimeout);
    flashTimersRef.current.clear();
  }, [selectedExpiry, symDef]);

  // "Updated Xs ago" counter — ticks every second, resets when lastRefresh changes
  useEffect(() => {
    if (!lastRefresh) { setSecondsAgo(null); return; }
    setSecondsAgo(0);
    const id = setInterval(() => {
      setSecondsAgo(Math.round((Date.now() - lastRefresh.getTime()) / 1000));
    }, 1000);
    return () => clearInterval(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastRefresh]);

  // Max Pain — fetched per expiry, 60s refresh
  const { data: maxPainData } = useQuery({
    queryKey: ["maxpain", symDef.label, exchange, selectedExpiry],
    queryFn: () => getMaxPain(symDef.label, exchange, selectedExpiry ?? undefined),
    enabled: !!selectedExpiry,
    staleTime: 60 * 1000,
    gcTime: 5 * 60 * 1000,
    retry: 1,
  });
  const maxPainStrike = maxPainData?.max_pain_strike ?? null;

  // Scroll ATM row into view when chain loads
  useEffect(() => {
    if (atmStrike == null || !gridRef.current) return;
    const atmIdx = strikes.findIndex((s) => s.strike === atmStrike);
    if (atmIdx >= 0) {
      clearTimeout(scrollTimerRef.current);
      scrollTimerRef.current = setTimeout(() => {
        gridRef.current?.scrollTo(0, atmIdx, "vertical", 0, 80, { vAlign: "center" });
      }, 100);
    }
    return () => clearTimeout(scrollTimerRef.current);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chain]);

  // Flash detection — compare LTP on each strikes update, set flash state for changed cells
  useEffect(() => {
    if (strikes.length === 0) return;
    let anyChanged = false;
    for (const { strike, call, put } of strikes) {
      const cLtp = call?.ltp ?? call?.last_price ?? null;
      const pLtp = put?.ltp  ?? put?.last_price  ?? null;
      const cKey = `${strike}_CE`;
      const pKey = `${strike}_PE`;

      if (cLtp != null) {
        const prev = prevLtpRef.current.get(cKey);
        if (prev != null && cLtp !== prev) {
          const dir: "up" | "down" = cLtp > prev ? "up" : "down";
          flashStateRef.current.set(cKey, dir);
          const existing = flashTimersRef.current.get(cKey);
          if (existing) clearTimeout(existing);
          flashTimersRef.current.set(cKey, setTimeout(() => {
            flashStateRef.current.delete(cKey);
            flashTimersRef.current.delete(cKey);
            bumpFlashTick();
          }, 500));
          anyChanged = true;
        }
        prevLtpRef.current.set(cKey, cLtp);
      }
      if (pLtp != null) {
        const prev = prevLtpRef.current.get(pKey);
        if (prev != null && pLtp !== prev) {
          const dir: "up" | "down" = pLtp > prev ? "up" : "down";
          flashStateRef.current.set(pKey, dir);
          const existing = flashTimersRef.current.get(pKey);
          if (existing) clearTimeout(existing);
          flashTimersRef.current.set(pKey, setTimeout(() => {
            flashStateRef.current.delete(pKey);
            flashTimersRef.current.delete(pKey);
            bumpFlashTick();
          }, 500));
          anyChanged = true;
        }
        prevLtpRef.current.set(pKey, pLtp);
      }
    }
    if (anyChanged) bumpFlashTick();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strikes]);

  // Basket helpers
  const isInBasket = useCallback((strike: number, optionType: "CE" | "PE"): boolean =>
    basket.some((b) => b.strike === strike && b.optionType === optionType),
  [basket]);

  function addToBasket(strike: number, optionType: "CE" | "PE", ltp: number | null) {
    if (!selectedExpiry) return;
    setBasket((prev) => {
      if (prev.some((b) => b.strike === strike && b.optionType === optionType)) return prev;
      return [...prev, { strike, optionType, ltp, expiry: selectedExpiry }];
    });
    setBasketOpen(true);
  }

  function removeFromBasket(strike: number, optionType: "CE" | "PE") {
    setBasket((prev) => prev.filter((b) => !(b.strike === strike && b.optionType === optionType)));
  }

  // Normalize an expiry string (YYYY-MM-DD or ISO) to DDMMMYY (e.g. 27MAR25)
  // as required by the OpenAlgo fallback symbol format.
  function normalizeExpiryForSymbol(expiry: string): string {
    try {
      const d = new Date(expiry);
      if (isNaN(d.getTime())) return expiry;
      const dd  = String(d.getDate()).padStart(2, "0");
      const mon = d.toLocaleString("en-US", { month: "short", timeZone: "UTC" }).toUpperCase();
      const yy  = String(d.getUTCFullYear()).slice(-2);
      return `${dd}${mon}${yy}`;
    } catch {
      return expiry;
    }
  }

  // Order placement — resolves canonical trading symbol via getOptionSymbol
  async function handleOrder({ strike, optionType, expiry, action }: OrderParams) {
    const normalizedExpiry = normalizeExpiryForSymbol(expiry);
    let orderSymbol   = `${symDef.label}${normalizedExpiry}${strike}${optionType}`;
    let orderExchange = exchange;
    try {
      const resolved = await getOptionSymbol(symDef.label, exchange, expiry, optionType, String(strike));
      orderSymbol   = resolved.symbol;
      orderExchange = resolved.exchange;
    } catch {
      // Fall back to manually constructed symbol
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
      clearTimeout(orderMsgTimerRef.current);
      orderMsgTimerRef.current = setTimeout(() => setOrderMsg(null), 3000);
    }
  }

  // Synthetic future — NFO/BFO only
  const showSyntheticFuture = exchange === "NFO" || exchange === "BFO";
  const { data: syntheticFutureData } = useSyntheticFuture(
    symDef.label,
    exchange,
    selectedExpiry ?? undefined,
  );

  const expiryButtons = expiries.slice(0, 5);

  // Glide grid config
  const glideColumns = useMemo(() => getColumns(view), [view]);

  const getCellContent = useCallback(
    (item: Item) =>
      buildGetCellContent({ view, columns: glideColumns, strikes, atmStrike, maxCallOI, maxPutOI, isInBasket, flashState: flashStateRef.current })(
        item as [number, number],
      ),
    // flashTick intentionally included: forces re-evaluation when flash state changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [view, glideColumns, strikes, atmStrike, maxCallOI, maxPutOI, isInBasket, flashTick],
  );

  const handleCellClicked = useCallback(([col, row]: Item) => {
    const colId = glideColumns[col]?.id ?? "";
    if (colId !== "c_act" && colId !== "p_act") return;
    const strikeRow = strikes[row];
    if (!strikeRow) return;
    const { strike, call, put } = strikeRow;
    const isCE = colId === "c_act";
    const optionType = isCE ? "CE" : "PE" as "CE" | "PE";
    const ltp  = isCE
      ? (call?.ltp ?? call?.last_price ?? null)
      : (put?.ltp  ?? put?.last_price  ?? null);

    if (legBuilderOpen) {
      // When LegBuilder is open, route the click into it
      legBuilderRef.current?.addLegFromStrike(strike, optionType);
      return;
    }

    if (isInBasket(strike, optionType)) {
      removeFromBasket(strike, optionType);
    } else {
      addToBasket(strike, optionType, ltp);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [glideColumns, strikes, isInBasket, legBuilderOpen]);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden select-none">

      {/* Top bar */}
      <div className="flex-none bg-surface-card border-b border-border-default px-2 py-1.5 space-y-1.5">

        {/* Row 1: Symbol + Exchange + Expiry + View + Basket + Refresh */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <SymbolSearch
            activeSymbol={symDef}
            onSelect={(newSym) => { setSymDef(newSym); setExchangeOverride(null); }}
            instruments={optionInstruments}
          />

          <ExchangeSelector value={exchange} onChange={setExchangeOverride} />

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
          <div role="radiogroup" aria-label="Option chain view" className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
            {VIEWS.map((v) => (
              <button
                key={v}
                role="radio"
                aria-checked={v === view}
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

          {/* Build Strategy button */}
          <button
            onClick={() => setLegBuilderOpen((p) => !p)}
            className={`flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded border transition-colors ${
              legBuilderOpen
                ? "bg-accent/15 border-accent/50 text-accent"
                : "bg-surface-hover border-border-default text-text-muted hover:text-text-primary hover:border-accent/30"
            }`}
            title="Build multi-leg option strategy"
            aria-pressed={legBuilderOpen}
          >
            <Layers size={11} />
            <span className="hidden sm:inline">Strategy</span>
          </button>

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
            onClick={() => void fetchData()}
            disabled={loading}
            className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors disabled:opacity-40"
            title="Refresh"
          >
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          </button>
        </div>

        {/* Row 2: Spot LTP + change% + PCR badge */}
        <div className="flex items-center gap-3 flex-wrap">
          {spotLtp != null ? (
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-text-muted uppercase tracking-wide">Spot</span>
              <span className="font-mono text-sm font-bold text-text-primary">{NUM.format(spotLtp)}</span>
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
          ) : (
            <span className="text-xs text-text-muted">Spot: —</span>
          )}

          {symbolDetails?.lotsize != null && symbolDetails.lotsize > 0 && (
            <div className="flex items-center gap-1 px-2 py-0.5 rounded border bg-surface-card border-border-default text-xs font-mono">
              <span className="text-text-muted font-sans">Lot</span>
              <span className="font-semibold text-text-primary">{NUM0.format(symbolDetails.lotsize)}</span>
            </div>
          )}

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

          {secondsAgo != null && (
            <div className="flex items-center gap-1 ml-auto text-xxs text-text-muted" title={lastRefresh?.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}>
              <RefreshCw size={9} className={loading ? "animate-spin" : ""} />
              {secondsAgo < 5
                ? "Just updated"
                : `Updated ${secondsAgo}s ago`}
            </div>
          )}
        </div>

        {/* OI signal legend + Max Pain */}
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
            {maxPainStrike != null && (
              <span className="px-2 py-0.5 rounded text-xxs font-medium bg-accent/20 text-accent border border-accent/30 font-mono">
                Max Pain: {maxPainStrike.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
              </span>
            )}
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
        <BasketPanel
          basket={basket}
          symLabel={symDef.label}
          exchange={exchange}
          onRemove={removeFromBasket}
          onClear={() => setBasket([])}
          onOrder={handleOrder}
        />
      )}

      {/* Leg builder panel */}
      {legBuilderOpen && (
        <LegBuilder
          ref={legBuilderRef}
          strikes={strikes}
          atmStrike={atmStrike}
          lotSize={symbolDetails?.lotsize ?? 1}
          symLabel={symDef.label}
          exchange={exchange}
          expiry={selectedExpiry}
          onClose={() => setLegBuilderOpen(false)}
        />
      )}

      {/* Chain table — Glide Data Grid */}
      {/* sr-only summary: screen readers see canvas content via this live region */}
      <div className="sr-only" role="status" aria-live="polite">
        Option chain: {strikes.length} strikes loaded for {symDef.label}
        {atmStrike != null ? `, ATM strike ${atmStrike}` : ""}
      </div>
      <div
        className="flex-1 min-h-0"
        role="grid"
        aria-label="Option chain data"
        aria-rowcount={strikes.length}
      >
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
          <>
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
                  return s.strike === atmStrike ? ATM_ROW_THEME : undefined;
                },
              } as object)}
            />
            {/* Visually-hidden HTML table mirror of the canvas grid.
                Canvas-rendered cells are invisible to screen readers, so we
                duplicate the data as a real <table> with tabular semantics.
                sr-only keeps it off the visible layout; position: absolute
                with negative clip means it still receives focus traversal. */}
            <table className="sr-only" aria-label="Option chain data (accessible view)">
              <caption>
                Option chain for {symDef.label}, expiry {selectedExpiry ?? "—"}.
                {atmStrike != null ? ` ATM strike ${atmStrike}.` : ""}
              </caption>
              <thead>
                <tr>
                  <th scope="col">Call OI</th>
                  <th scope="col">Call change</th>
                  <th scope="col">Call volume</th>
                  <th scope="col">Call IV</th>
                  <th scope="col">Call LTP</th>
                  <th scope="col">Strike</th>
                  <th scope="col">Put LTP</th>
                  <th scope="col">Put IV</th>
                  <th scope="col">Put volume</th>
                  <th scope="col">Put change</th>
                  <th scope="col">Put OI</th>
                </tr>
              </thead>
              <tbody>
                {strikes.map((s) => (
                  <tr key={s.strike} aria-current={s.strike === atmStrike ? "true" : undefined}>
                    <td>{s.call?.oi ?? s.call?.open_interest ?? 0}</td>
                    <td>{s.call?.change ?? 0}</td>
                    <td>{s.call?.volume ?? 0}</td>
                    <td>{s.call?.iv ?? ""}</td>
                    <td>{s.call?.ltp ?? s.call?.last_price ?? 0}</td>
                    <th scope="row">{s.strike}</th>
                    <td>{s.put?.ltp ?? s.put?.last_price ?? 0}</td>
                    <td>{s.put?.iv ?? ""}</td>
                    <td>{s.put?.volume ?? 0}</td>
                    <td>{s.put?.change ?? 0}</td>
                    <td>{s.put?.oi ?? s.put?.open_interest ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
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

export default memo(OptionChainWidget);
