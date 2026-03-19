/**
 * OptionChainWidget — production-grade option chain for FlintTrade terminal.
 *
 * Features:
 *   - Symbol + Exchange selectors, first-5 expiry buttons
 *   - Spot LTP, change, change%, PCR badge
 *   - Three view tabs: LTP | OI | GREEKS
 *   - Scrollable chain table: 10 strikes above ATM, ATM row highlighted, 10 below
 *   - Buy/Sell mini buttons per strike (calls + puts)
 *   - Color-coded change%, OI bars, ATM accent border
 *   - Auto-refresh: 3 s market hours, 30 s off-hours
 *   - Dense layout: text-xs data, text-[10px] headers, font-mono numbers
 */

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { RefreshCw, ChevronDown, TrendingUp, TrendingDown, AlertCircle } from "lucide-react";
import { getExpiry, getOptionChain, getQuotes, placeOrder } from "../../../services/api";
import type { Quote } from "../../../types/api";

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
  iv?: number;
  implied_volatility?: number;
}

/** OpenAlgo optionchain raw API shape */
interface RawOptionChain {
  calls?: RawOptionRow[];
  puts?: RawOptionRow[];
  atm_strike?: number;
  pcr?: number;
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

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SYMBOLS: SymbolDef[] = [
  { label: "NIFTY",      exchange: "NFO", spotSymbol: "NIFTY",      spotExchange: "NSE_INDEX" },
  { label: "BANKNIFTY",  exchange: "NFO", spotSymbol: "BANKNIFTY",  spotExchange: "NSE_INDEX" },
  { label: "FINNIFTY",   exchange: "NFO", spotSymbol: "FINNIFTY",   spotExchange: "NSE_INDEX" },
  { label: "MIDCPNIFTY", exchange: "NFO", spotSymbol: "MIDCPNIFTY", spotExchange: "NSE_INDEX" },
  { label: "SENSEX",     exchange: "BFO", spotSymbol: "SENSEX",     spotExchange: "BSE_INDEX" },
];

const EXCHANGES = ["NFO", "BFO"];
const VIEWS: ViewType[] = ["LTP", "OI", "GREEKS"];
const STRIKES_AROUND_ATM = 10;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isMarketHours(): boolean {
  const now = new Date();
  const ist = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
  const day = ist.getDay();
  if (day === 0 || day === 6) return false;
  const mins = ist.getHours() * 60 + ist.getMinutes();
  return mins >= 555 && mins <= 930;
}

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

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface BuySellButtonsProps {
  symbol: string;
  exchange: string;
  strike: number;
  optionType: string;
  expiry: string | null;
  ltp: number | null;
  onOrder: (params: OrderParams) => Promise<void>;
}

function BuySellButtons({ symbol, exchange, strike, optionType, expiry, ltp, onOrder }: BuySellButtonsProps) {
  const [loading, setLoading] = useState<"B" | "S" | null>(null);

  async function handleClick(action: "B" | "S") {
    if (!symbol || !expiry) return;
    setLoading(action);
    try {
      await onOrder({ symbol, exchange, strike, optionType, expiry, action, ltp });
    } catch {
      // parent handles errors
    } finally {
      setLoading(null);
    }
  }

  return (
    <div className="flex gap-0.5">
      <button
        onClick={() => handleClick("B")}
        disabled={!!loading}
        className="px-1 py-0.5 text-[9px] font-semibold rounded bg-profit/10 text-profit hover:bg-profit/25 border border-profit/20 hover:border-profit/50 transition-colors disabled:opacity-40 leading-none"
      >
        {loading === "B" ? "…" : "B"}
      </button>
      <button
        onClick={() => handleClick("S")}
        disabled={!!loading}
        className="px-1 py-0.5 text-[9px] font-semibold rounded bg-loss/10 text-loss hover:bg-loss/25 border border-loss/20 hover:border-loss/50 transition-colors disabled:opacity-40 leading-none"
      >
        {loading === "S" ? "…" : "S"}
      </button>
    </div>
  );
}

interface OIBarProps {
  value: number | null | undefined;
  maxValue: number;
  side: "call" | "put";
}

function OIBar({ value, maxValue, side }: OIBarProps) {
  if (!value || !maxValue) return null;
  const pct = Math.min((Number(value) / Number(maxValue)) * 100, 100);
  return (
    <div className="absolute inset-y-0 w-full flex items-center pointer-events-none">
      {side === "call" ? (
        <div
          className="absolute right-0 h-[60%] bg-loss/8 rounded-l"
          style={{ width: `${pct}%` }}
        />
      ) : (
        <div
          className="absolute left-0 h-[60%] bg-profit/8 rounded-r"
          style={{ width: `${pct}%` }}
        />
      )}
    </div>
  );
}

interface SelectorProps {
  value: string;
  options: string[];
  onChange: (val: string) => void;
  className?: string;
}

function Selector({ value, options, onChange, className = "" }: SelectorProps) {
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
    <div ref={ref} className={`relative ${className}`}>
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-text-primary bg-surface-hover border border-border-default rounded hover:border-accent/50 transition-colors"
      >
        {value}
        <ChevronDown size={10} className={`transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-0.5 z-50 bg-surface-card border border-border-default rounded shadow-lg min-w-full">
          {options.map((opt) => (
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
  const [activeSymbolIdx, setActiveSymbolIdx] = useState(0);
  const [exchangeOverride, setExchangeOverride] = useState<string | null>(null);
  const [expiries, setExpiries] = useState<string[]>([]);
  const [selectedExpiry, setSelectedExpiry] = useState<string | null>(null);
  const [view, setView] = useState<ViewType>("LTP");

  const [chain, setChain] = useState<RawOptionChain | null>(null);
  const [spot, setSpot]   = useState<Quote | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const [orderMsg, setOrderMsg] = useState<OrderToast | null>(null);

  const symDef   = SYMBOLS[activeSymbolIdx];
  const exchange = exchangeOverride ?? symDef.exchange;

  const atmRowRef   = useRef<HTMLTableRowElement | null>(null);
  const tableBodyRef = useRef<HTMLDivElement | null>(null);

  // fetch expiries when symbol/exchange changes
  useEffect(() => {
    setExpiries([]);
    setSelectedExpiry(null);
    setChain(null);
    setError(null);

    let cancelled = false;
    (async () => {
      try {
        const data = await getExpiry(symDef.label, exchange);
        if (cancelled) return;
        const list = Array.isArray(data) ? data as string[] : ((data as { expiry?: string[] })?.expiry ?? []);
        setExpiries(list);
        if (list.length > 0) setSelectedExpiry(list[0]);
      } catch (e) {
        if (!cancelled) setError(`Failed to load expiries: ${(e as Error).message}`);
      }
    })();

    return () => { cancelled = true; };
  }, [activeSymbolIdx, exchange, symDef.label]);

  // fetch chain + spot
  const fetchData = useCallback(async () => {
    if (!selectedExpiry) return;
    setLoading(true);
    setError(null);

    try {
      const [chainData, spotData] = await Promise.allSettled([
        getOptionChain(symDef.label, exchange, selectedExpiry),
        getQuotes(symDef.spotSymbol, symDef.spotExchange),
      ]);

      if (chainData.status === "fulfilled") {
        setChain(chainData.value as unknown as RawOptionChain);
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
  }, [selectedExpiry, symDef, exchange]);

  // auto-refresh
  useEffect(() => {
    fetchData();
    const interval = isMarketHours() ? 3000 : 30000;
    const id = setInterval(fetchData, interval);
    return () => clearInterval(id);
  }, [fetchData]);

  // scroll ATM into view when chain loads
  useEffect(() => {
    if (atmRowRef.current && tableBodyRef.current) {
      setTimeout(() => {
        atmRowRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
      }, 100);
    }
  }, [chain]);

  // compute ordered strike list, ATM, max OI
  // maxPutOI is computed for future OI bar on the put side (reserved for Glide Data Grid migration)
  const { strikes, atmStrike, maxCallOI } = useMemo(() => {
    if (!chain) return { strikes: [] as StrikeRow[], atmStrike: null as number | null, maxCallOI: 0 };

    const callMap: Record<number, RawOptionRow> = {};
    const putMap:  Record<number, RawOptionRow> = {};

    (chain.calls ?? []).forEach((c) => { callMap[c.strike_price ?? c.strike ?? 0] = c; });
    (chain.puts  ?? []).forEach((p) => { putMap[p.strike_price  ?? p.strike  ?? 0] = p; });

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

    const maxCallOI = Math.max(0, ...visible.map((s) => Number(callMap[s]?.oi ?? 0)));

    return {
      strikes: visible.map((s) => ({ strike: s, call: callMap[s] ?? null, put: putMap[s] ?? null })),
      atmStrike: atm,
      maxCallOI,
    };
  }, [chain, spot]);

  // spot derived values
  const spotLtp      = spot?.ltp ?? null;
  const spotPrevClose = (spot as unknown as { prev_close?: number })?.prev_close ?? spot?.close ?? null;
  const spotChange   = spotLtp && spotPrevClose ? spotLtp - spotPrevClose : null;
  const spotChangePct = spotChange && spotPrevClose ? (spotChange / spotPrevClose) * 100 : null;
  const spotUp       = spotChange == null ? null : spotChange >= 0;

  // order handler
  async function handleOrder({ strike, optionType, expiry, action }: OrderParams) {
    const orderSymbol = `${symDef.label}${expiry}${strike}${optionType}`;
    try {
      await placeOrder({
        strategy: "FlintChain",
        symbol: orderSymbol,
        exchange,
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

  const pcr = chain?.pcr ?? null;
  const expiryButtons = expiries.slice(0, 5);

  // render helpers
  function renderCallCells(call: RawOptionRow | null, strike: number) {
    if (!call) {
      return (
        <>
          <td className="px-1 py-0.5 text-right font-mono text-text-muted">—</td>
          <td className="px-1 py-0.5 text-right font-mono text-text-muted">—</td>
          {view !== "GREEKS" && <td className="px-1 py-0.5 text-right font-mono text-text-muted">—</td>}
          <td className="px-1 py-0.5 text-center"></td>
        </>
      );
    }
    const ltp    = call.ltp ?? call.last_price ?? null;
    const chgPct = call.change_percent ?? call.change_pct ?? null;
    const oi     = call.oi ?? call.open_interest ?? null;
    const oiChg  = call.oi_change ?? null;
    const delta  = call.delta ?? null;
    const iv     = call.iv ?? call.implied_volatility ?? null;
    const chgUp  = chgPct == null ? null : Number(chgPct) >= 0;

    if (view === "LTP") {
      return (
        <>
          <td className={`px-1 py-0.5 text-right font-mono text-xs ${chgUp === true ? "text-profit" : chgUp === false ? "text-loss" : "text-text-muted"}`}>
            {fmtChg(chgPct)}
          </td>
          <td className="px-1 py-0.5 text-right font-mono text-xs text-text-primary">{fmtLtp(ltp)}</td>
          <td className="px-1 py-0.5 text-right font-mono text-xs text-text-secondary">{fmtOI(oi)}</td>
          <td className="px-1 py-0.5 text-center">
            <BuySellButtons
              symbol={symDef.label} exchange={exchange}
              strike={strike} optionType="CE" expiry={selectedExpiry}
              ltp={ltp} onOrder={handleOrder}
            />
          </td>
        </>
      );
    }

    if (view === "OI") {
      const oiChgUp = oiChg == null ? null : Number(oiChg) >= 0;
      return (
        <>
          <td className={`px-1 py-0.5 text-right font-mono text-xs ${oiChgUp === true ? "text-profit" : oiChgUp === false ? "text-loss" : "text-text-muted"}`}>
            {oiChg != null ? `${Number(oiChg) >= 0 ? "+" : ""}${fmtOI(Math.abs(oiChg))}` : "—"}
          </td>
          <td className="px-1 py-0.5 text-right font-mono text-xs text-text-secondary">{fmtOI(oi)}</td>
          <td className="px-1 py-0.5 text-right font-mono text-xs text-text-primary">{fmtLtp(ltp)}</td>
          <td className="px-1 py-0.5 text-center">
            <BuySellButtons
              symbol={symDef.label} exchange={exchange}
              strike={strike} optionType="CE" expiry={selectedExpiry}
              ltp={ltp} onOrder={handleOrder}
            />
          </td>
        </>
      );
    }

    // GREEKS view
    return (
      <>
        <td className="px-1 py-0.5 text-right font-mono text-xs text-text-secondary">{fmtIV(iv)}</td>
        <td className="px-1 py-0.5 text-right font-mono text-xs text-text-primary">{fmtDelta(delta)}</td>
        <td className="px-1 py-0.5 text-right font-mono text-xs text-text-secondary">{fmtLtp(ltp)}</td>
        <td className="px-1 py-0.5 text-center">
          <BuySellButtons
            symbol={symDef.label} exchange={exchange}
            strike={strike} optionType="CE" expiry={selectedExpiry}
            ltp={ltp} onOrder={handleOrder}
          />
        </td>
      </>
    );
  }

  function renderPutCells(put: RawOptionRow | null, strike: number) {
    if (!put) {
      return (
        <>
          <td className="px-1 py-0.5 text-center"></td>
          <td className="px-1 py-0.5 text-left font-mono text-text-muted">—</td>
          <td className="px-1 py-0.5 text-left font-mono text-text-muted">—</td>
          {view !== "GREEKS" && <td className="px-1 py-0.5 text-left font-mono text-text-muted">—</td>}
        </>
      );
    }
    const ltp    = put.ltp ?? put.last_price ?? null;
    const chgPct = put.change_percent ?? put.change_pct ?? null;
    const oi     = put.oi ?? put.open_interest ?? null;
    const oiChg  = put.oi_change ?? null;
    const delta  = put.delta ?? null;
    const iv     = put.iv ?? put.implied_volatility ?? null;
    const chgUp  = chgPct == null ? null : Number(chgPct) >= 0;

    if (view === "LTP") {
      return (
        <>
          <td className="px-1 py-0.5 text-center">
            <BuySellButtons
              symbol={symDef.label} exchange={exchange}
              strike={strike} optionType="PE" expiry={selectedExpiry}
              ltp={ltp} onOrder={handleOrder}
            />
          </td>
          <td className="px-1 py-0.5 text-left font-mono text-xs text-text-primary">{fmtLtp(ltp)}</td>
          <td className={`px-1 py-0.5 text-left font-mono text-xs ${chgUp === true ? "text-profit" : chgUp === false ? "text-loss" : "text-text-muted"}`}>
            {fmtChg(chgPct)}
          </td>
          <td className="px-1 py-0.5 text-left font-mono text-xs text-text-secondary">{fmtOI(oi)}</td>
        </>
      );
    }

    if (view === "OI") {
      const oiChgUp = oiChg == null ? null : Number(oiChg) >= 0;
      return (
        <>
          <td className="px-1 py-0.5 text-center">
            <BuySellButtons
              symbol={symDef.label} exchange={exchange}
              strike={strike} optionType="PE" expiry={selectedExpiry}
              ltp={ltp} onOrder={handleOrder}
            />
          </td>
          <td className="px-1 py-0.5 text-left font-mono text-xs text-text-primary">{fmtLtp(ltp)}</td>
          <td className="px-1 py-0.5 text-left font-mono text-xs text-text-secondary">{fmtOI(oi)}</td>
          <td className={`px-1 py-0.5 text-left font-mono text-xs ${oiChgUp === true ? "text-profit" : oiChgUp === false ? "text-loss" : "text-text-muted"}`}>
            {oiChg != null ? `${Number(oiChg) >= 0 ? "+" : ""}${fmtOI(Math.abs(oiChg))}` : "—"}
          </td>
        </>
      );
    }

    // GREEKS
    return (
      <>
        <td className="px-1 py-0.5 text-center">
          <BuySellButtons
            symbol={symDef.label} exchange={exchange}
            strike={strike} optionType="PE" expiry={selectedExpiry}
            ltp={ltp} onOrder={handleOrder}
          />
        </td>
        <td className="px-1 py-0.5 text-left font-mono text-xs text-text-secondary">{fmtLtp(ltp)}</td>
        <td className="px-1 py-0.5 text-left font-mono text-xs text-text-primary">{fmtDelta(delta)}</td>
        <td className="px-1 py-0.5 text-left font-mono text-xs text-text-secondary">{fmtIV(iv)}</td>
      </>
    );
  }

  function CallHeaders() {
    if (view === "LTP")    return <><th className="px-1 py-1 text-right text-[10px] text-loss/80 uppercase tracking-wide">Chg%</th><th className="px-1 py-1 text-right text-[10px] text-text-muted uppercase tracking-wide">LTP</th><th className="px-1 py-1 text-right text-[10px] text-text-muted uppercase tracking-wide">OI</th><th className="px-1 py-1 text-center text-[10px] text-text-muted uppercase tracking-wide w-12">Action</th></>;
    if (view === "OI")     return <><th className="px-1 py-1 text-right text-[10px] text-text-muted uppercase tracking-wide">OI Chg</th><th className="px-1 py-1 text-right text-[10px] text-text-muted uppercase tracking-wide">OI</th><th className="px-1 py-1 text-right text-[10px] text-text-muted uppercase tracking-wide">LTP</th><th className="px-1 py-1 text-center text-[10px] text-text-muted uppercase tracking-wide w-12">Action</th></>;
    return <><th className="px-1 py-1 text-right text-[10px] text-text-muted uppercase tracking-wide">IV</th><th className="px-1 py-1 text-right text-[10px] text-text-muted uppercase tracking-wide">Delta</th><th className="px-1 py-1 text-right text-[10px] text-text-muted uppercase tracking-wide">LTP</th><th className="px-1 py-1 text-center text-[10px] text-text-muted uppercase tracking-wide w-12">Action</th></>;
  }

  function PutHeaders() {
    if (view === "LTP")    return <><th className="px-1 py-1 text-center text-[10px] text-text-muted uppercase tracking-wide w-12">Action</th><th className="px-1 py-1 text-left text-[10px] text-text-muted uppercase tracking-wide">LTP</th><th className="px-1 py-1 text-left text-[10px] text-profit/80 uppercase tracking-wide">Chg%</th><th className="px-1 py-1 text-left text-[10px] text-text-muted uppercase tracking-wide">OI</th></>;
    if (view === "OI")     return <><th className="px-1 py-1 text-center text-[10px] text-text-muted uppercase tracking-wide w-12">Action</th><th className="px-1 py-1 text-left text-[10px] text-text-muted uppercase tracking-wide">LTP</th><th className="px-1 py-1 text-left text-[10px] text-text-muted uppercase tracking-wide">OI</th><th className="px-1 py-1 text-left text-[10px] text-text-muted uppercase tracking-wide">OI Chg</th></>;
    return <><th className="px-1 py-1 text-center text-[10px] text-text-muted uppercase tracking-wide w-12">Action</th><th className="px-1 py-1 text-left text-[10px] text-text-muted uppercase tracking-wide">LTP</th><th className="px-1 py-1 text-left text-[10px] text-text-muted uppercase tracking-wide">Delta</th><th className="px-1 py-1 text-left text-[10px] text-text-muted uppercase tracking-wide">IV</th></>;
  }

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden select-none">

      {/* Top bar */}
      <div className="flex-none bg-surface-card border-b border-border-default px-2 py-1.5 space-y-1.5">

        {/* Row 1 */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <Selector
            value={symDef.label}
            options={SYMBOLS.map((s) => s.label)}
            onChange={(val) => {
              const idx = SYMBOLS.findIndex((s) => s.label === val);
              setActiveSymbolIdx(idx);
              setExchangeOverride(null);
            }}
          />

          <Selector
            value={exchange}
            options={EXCHANGES}
            onChange={setExchangeOverride}
          />

          <div className="flex items-center gap-1">
            {expiryButtons.length === 0 && !loading && (
              <span className="text-[10px] text-text-muted px-1">No expiries</span>
            )}
            {expiryButtons.map((exp) => (
              <button
                key={exp}
                onClick={() => setSelectedExpiry(exp)}
                className={`px-2 py-0.5 text-[10px] font-medium rounded border transition-colors ${
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

          <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
            {VIEWS.map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={`px-2 py-0.5 text-[10px] font-medium transition-colors ${
                  v === view
                    ? "bg-accent/15 text-accent"
                    : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
                }`}
              >
                {v}
              </button>
            ))}
          </div>

          <button
            onClick={fetchData}
            disabled={loading}
            className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors disabled:opacity-40"
            title="Refresh"
          >
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          </button>
        </div>

        {/* Row 2: spot + PCR */}
        <div className="flex items-center gap-3 flex-wrap">
          {spotLtp != null ? (
            <>
              <div className="flex items-center gap-1">
                <span className="text-[10px] text-text-muted uppercase tracking-wide">Spot</span>
                <span className="font-mono text-sm font-semibold text-text-primary">
                  {NUM.format(spotLtp)}
                </span>
              </div>
              {spotChange != null && (
                <div className={`flex items-center gap-0.5 text-xs font-mono ${spotUp ? "text-profit" : "text-loss"}`}>
                  {spotUp ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
                  <span>{spotChange >= 0 ? "+" : ""}{spotChange.toFixed(2)}</span>
                  <span className="text-[10px]">({spotChangePct != null && spotChangePct >= 0 ? "+" : ""}{spotChangePct?.toFixed(2)}%)</span>
                </div>
              )}
            </>
          ) : (
            <span className="text-[10px] text-text-muted">Spot: —</span>
          )}

          {pcr != null && (
            <div className="flex items-center gap-1 ml-2">
              <span className="text-[10px] text-text-muted uppercase tracking-wide">PCR</span>
              <span className={`font-mono text-xs font-semibold ${
                Number(pcr) >= 1.2 ? "text-profit" : Number(pcr) <= 0.8 ? "text-loss" : "text-warning"
              }`}>
                {Number(pcr).toFixed(2)}
              </span>
            </div>
          )}

          {lastRefresh && (
            <div className="flex items-center gap-1 ml-auto text-[10px] text-text-muted">
              <RefreshCw size={9} />
              {lastRefresh.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}
            </div>
          )}
        </div>
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

      {/* Chain table */}
      <div className="flex-1 overflow-auto" ref={tableBodyRef}>
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
          <table className="w-full border-separate border-spacing-0">
            <thead className="sticky top-0 z-10 bg-surface-card">
              <tr className="border-b border-border-default">
                <CallHeaders />
                <th className="px-2 py-1 text-center text-[10px] text-accent uppercase tracking-wider w-16 border-x border-border-default">
                  STRIKE
                </th>
                <PutHeaders />
              </tr>
            </thead>

            <tbody>
              {strikes.map(({ strike, call, put }, idx) => {
                const isAtm = strike === atmStrike;
                const atmIdx = strikes.findIndex((s) => s.strike === atmStrike);
                const isNearAtm = Math.abs(idx - atmIdx) <= 2;

                const callOI = call?.oi ?? call?.open_interest ?? 0;

                return (
                  <tr
                    key={strike}
                    ref={isAtm ? atmRowRef : null}
                    className={`group border-b transition-colors ${
                      isAtm
                        ? "border-b-accent/40 bg-accent/5 border-t-accent/40"
                        : isNearAtm
                          ? "border-border-subtle bg-surface-hover/20 hover:bg-surface-hover/40"
                          : "border-border-subtle hover:bg-surface-hover/30"
                    }`}
                  >
                    <td className="relative" colSpan={0}>
                      <OIBar value={callOI} maxValue={maxCallOI} side="call" />
                    </td>
                    {renderCallCells(call, strike)}

                    <td className={`px-1 py-0.5 text-center font-mono text-xs font-semibold border-x ${
                      isAtm
                        ? "text-accent border-accent/40 bg-accent/10"
                        : "text-text-primary border-border-default"
                    }`}>
                      {isAtm && (
                        <span className="block text-[9px] text-accent/70 leading-none mb-0.5">ATM</span>
                      )}
                      {NUM0.format(strike)}
                    </td>

                    {renderPutCells(put, strike)}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Footer */}
      {chain && strikes.length > 0 && (
        <div className="flex-none bg-surface-card border-t border-border-default px-3 py-1 flex items-center gap-4 text-[10px]">
          <span className="text-text-muted uppercase tracking-wide">Total OI</span>
          <span className="text-loss font-mono">
            CE: {fmtOI(strikes.reduce((s, r) => s + Number(r.call?.oi ?? r.call?.open_interest ?? 0), 0))}
          </span>
          <span className="text-profit font-mono">
            PE: {fmtOI(strikes.reduce((s, r) => s + Number(r.put?.oi  ?? r.put?.open_interest  ?? 0), 0))}
          </span>
          {atmStrike != null && (
            <span className="text-text-muted ml-2">ATM: <span className="font-mono text-accent">{NUM0.format(atmStrike)}</span></span>
          )}
          <span className="ml-auto text-text-muted">
            {isMarketHours() ? "Live · 3s" : "Closed · 30s"}
          </span>
        </div>
      )}
    </div>
  );
}
