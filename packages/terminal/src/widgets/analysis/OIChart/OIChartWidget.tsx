/**
 * OIChartWidget — Open Interest horizontal bar chart for FlintTrade terminal.
 *
 * Features:
 *   - Symbol selector (NIFTY / BANKNIFTY / FINNIFTY / MIDCPNIFTY) + Exchange (NFO/BFO)
 *   - Expiry selector dropdown
 *   - Horizontal bar chart: Call OI bars LEFT (red tint), Put OI bars RIGHT (green tint)
 *   - ATM strike highlighted with spot LTP indicator line
 *   - Filter buttons: All | OI Increase | OI Decrease
 *   - PCR badge, Support/Resistance labels at max OI strikes
 *   - Pure CSS bar widths proportional to max OI — no chart library
 *   - Auto-refresh: 5s market hours, 30s off-market
 */

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { RefreshCw, ChevronDown, AlertCircle } from "lucide-react";
import { getExpiry, getOptionChain, getQuotes } from "../../../services/api";
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

type FilterType = "All" | "OI Increase" | "OI Decrease";

interface RawOptionRow {
  strike_price?: number;
  strike?: number;
  oi?: number;
  open_interest?: number;
}

interface RawOptionChain {
  calls?: RawOptionRow[];
  puts?: RawOptionRow[];
  atm_strike?: number;
  pcr?: number;
}

interface OIRowData {
  strike: number;
  callOI: number;
  putOI: number;
  callOIChange: number;
  putOIChange: number;
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

const FILTERS: FilterType[] = ["All", "OI Increase", "OI Decrease"];
const STRIKES_AROUND_ATM = 15;

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

const NUM0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

function fmtOI(v: number | null | undefined): string {
  if (v == null || v === 0) return "0";
  const n = Number(v);
  if (n >= 1_00_00_000) return `${(n / 1_00_00_000).toFixed(1)}Cr`;
  if (n >= 1_00_000)    return `${(n / 1_00_000).toFixed(1)}L`;
  if (n >= 1_000)       return `${(n / 1_000).toFixed(1)}K`;
  return NUM0.format(n);
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
// OI Bar Row
// ---------------------------------------------------------------------------

interface OIRowProps {
  strike: number;
  callOI: number;
  putOI: number;
  maxOI: number;
  isAtm: boolean;
  isMaxCall: boolean;
  isMaxPut: boolean;
  spotLtp: number | null;
}

function OIRow({ strike, callOI, putOI, maxOI, isAtm, isMaxCall, isMaxPut, spotLtp }: OIRowProps) {
  const callPct = maxOI > 0 ? Math.min((callOI / maxOI) * 100, 100) : 0;
  const putPct  = maxOI > 0 ? Math.min((putOI  / maxOI) * 100, 100) : 0;

  return (
    <div
      className={`flex items-center text-xs h-6.5 border-b transition-colors ${
        isAtm
          ? "border-b-accent/40 bg-accent/6"
          : "border-border-subtle hover:bg-surface-hover/30"
      }`}
    >
      {/* Call OI bar side (left, right-aligned) */}
      <div className="flex-1 flex items-center justify-end pr-1 relative h-full overflow-hidden">
        <div
          className="absolute right-0 top-1/2 -translate-y-1/2 h-3.5 rounded-l-sm transition-all duration-300"
          style={{
            width: `${callPct}%`,
            background: callPct > 75
              ? "rgba(239,68,68,0.35)"
              : callPct > 40
                ? "rgba(239,68,68,0.22)"
                : "rgba(239,68,68,0.12)",
          }}
        />
        <span className={`relative z-10 font-mono ${isMaxCall ? "text-loss font-semibold" : "text-text-secondary"}`}>
          {fmtOI(callOI)}
        </span>
        {isMaxCall && (
          <span className="relative z-10 ml-1 text-xxs text-loss/80 font-medium leading-none px-0.5 py-0.5 rounded bg-loss/10 border border-loss/20">
            R
          </span>
        )}
      </div>

      {/* Strike label */}
      <div
        className={`flex-none w-18 text-center font-mono font-semibold border-x px-1 h-full flex flex-col items-center justify-center ${
          isAtm
            ? "text-accent border-accent/40 bg-accent/10"
            : "text-text-primary border-border-default"
        }`}
      >
        {isAtm && (
          <span className="text-xxs text-accent/70 leading-none">ATM</span>
        )}
        {NUM0.format(strike)}
        {isAtm && spotLtp != null && (
          <span className="text-xxs text-text-muted font-normal font-sans leading-none">
            {spotLtp.toLocaleString("en-IN", { maximumFractionDigits: 1 })}
          </span>
        )}
      </div>

      {/* Put OI bar side (right, left-aligned) */}
      <div className="flex-1 flex items-center pl-1 relative h-full overflow-hidden">
        <div
          className="absolute left-0 top-1/2 -translate-y-1/2 h-3.5 rounded-r-sm transition-all duration-300"
          style={{
            width: `${putPct}%`,
            background: putPct > 75
              ? "rgba(34,197,94,0.35)"
              : putPct > 40
                ? "rgba(34,197,94,0.22)"
                : "rgba(34,197,94,0.12)",
          }}
        />
        {isMaxPut && (
          <span className="relative z-10 mr-1 text-xxs text-profit/80 font-medium leading-none px-0.5 py-0.5 rounded bg-profit/10 border border-profit/20">
            S
          </span>
        )}
        <span className={`relative z-10 font-mono ${isMaxPut ? "text-profit font-semibold" : "text-text-secondary"}`}>
          {fmtOI(putOI)}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

interface OIChartWidgetProps {
  node?: FlexLayoutNode;
}

export default function OIChartWidget({ node: _node }: OIChartWidgetProps) {
  const [activeSymbolIdx, setActiveSymbolIdx] = useState(0);
  const [expiries, setExpiries] = useState<string[]>([]);
  const [selectedExpiry, setSelectedExpiry] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterType>("All");

  const [chain, setChain]     = useState<RawOptionChain | null>(null);
  const [spot, setSpot]       = useState<Quote | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const prevOIRef = useRef<Record<string, number>>({});

  const symDef   = SYMBOLS[activeSymbolIdx];
  const exchange = symDef.exchange;

  // fetch expiries
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
        if (!cancelled) setError(`Expiry load failed: ${(e as Error).message}`);
      }
    })();

    return () => { cancelled = true; };
  }, [activeSymbolIdx, symDef.label, exchange]);

  // fetch chain + spot
  const fetchData = useCallback(async () => {
    if (!selectedExpiry) return;
    setLoading(true);
    setError(null);

    try {
      const [chainRes, spotRes] = await Promise.allSettled([
        getOptionChain(symDef.label, exchange, selectedExpiry),
        getQuotes(symDef.spotSymbol, symDef.spotExchange),
      ]);

      if (chainRes.status === "fulfilled") {
        const newChain = chainRes.value as unknown as RawOptionChain;
        const snapshot: Record<string, number> = {};
        (newChain.calls ?? []).forEach((c) => {
          const k = `${c.strike_price ?? c.strike}_CE`;
          snapshot[k] = Number(c.oi ?? c.open_interest ?? 0);
        });
        (newChain.puts ?? []).forEach((p) => {
          const k = `${p.strike_price ?? p.strike}_PE`;
          snapshot[k] = Number(p.oi ?? p.open_interest ?? 0);
        });
        prevOIRef.current = snapshot;
        setChain(newChain);
      } else {
        setError(`Chain error: ${(chainRes.reason as Error)?.message}`);
      }

      if (spotRes.status === "fulfilled") {
        setSpot(spotRes.value);
      }
    } finally {
      setLoading(false);
      setLastRefresh(new Date());
    }
  }, [selectedExpiry, symDef, exchange]);

  // auto-refresh
  useEffect(() => {
    fetchData();
    const interval = isMarketHours() ? 5000 : 30000;
    const id = setInterval(fetchData, interval);
    return () => clearInterval(id);
  }, [fetchData]);

  // computed strike rows
  const { rows, atmStrike, maxOI, totalCallOI, totalPutOI, pcr, maxCallStrike, maxPutStrike } = useMemo(() => {
    if (!chain) {
      return {
        rows: [] as OIRowData[],
        atmStrike: null as number | null,
        maxOI: 0,
        totalCallOI: 0,
        totalPutOI: 0,
        pcr: null as number | null,
        maxCallStrike: null as number | null,
        maxPutStrike: null as number | null,
      };
    }

    const callMap: Record<number, RawOptionRow> = {};
    const putMap:  Record<number, RawOptionRow> = {};

    (chain.calls ?? []).forEach((c) => { callMap[c.strike_price ?? c.strike ?? 0] = c; });
    (chain.puts  ?? []).forEach((p) => { putMap[p.strike_price  ?? p.strike  ?? 0] = p; });

    const allStrikes = Array.from(
      new Set([...Object.keys(callMap).map(Number), ...Object.keys(putMap).map(Number)])
    ).sort((a, b) => a - b);

    const spotLtp = spot?.ltp ?? null;
    const atm = chain.atm_strike ?? (spotLtp
      ? allStrikes.reduce((prev, cur) =>
          Math.abs(cur - spotLtp) < Math.abs(prev - spotLtp) ? cur : prev,
          allStrikes[0] ?? 0)
      : allStrikes[Math.floor(allStrikes.length / 2)] ?? null);

    const atmIdx = allStrikes.indexOf(atm ?? 0);
    const lo = Math.max(0, atmIdx - STRIKES_AROUND_ATM);
    const hi = Math.min(allStrikes.length - 1, atmIdx + STRIKES_AROUND_ATM);
    const visible = allStrikes.slice(lo, hi + 1);

    let rawRows: OIRowData[] = visible.map((s) => {
      const callOI = Number(callMap[s]?.oi ?? callMap[s]?.open_interest ?? 0);
      const putOI  = Number(putMap[s]?.oi  ?? putMap[s]?.open_interest  ?? 0);
      const prevCallOI = prevOIRef.current[`${s}_CE`] ?? callOI;
      const prevPutOI  = prevOIRef.current[`${s}_PE`] ?? putOI;
      return {
        strike: s,
        callOI,
        putOI,
        callOIChange: callOI - prevCallOI,
        putOIChange:  putOI  - prevPutOI,
      };
    });

    if (filter === "OI Increase") {
      rawRows = rawRows.filter((r) => r.callOIChange > 0 || r.putOIChange > 0);
    } else if (filter === "OI Decrease") {
      rawRows = rawRows.filter((r) => r.callOIChange < 0 || r.putOIChange < 0);
    }

    const maxOI = Math.max(
      0,
      ...rawRows.map((r) => r.callOI),
      ...rawRows.map((r) => r.putOI),
    );

    const totalCallOI = rawRows.reduce((s, r) => s + r.callOI, 0);
    const totalPutOI  = rawRows.reduce((s, r) => s + r.putOI,  0);
    const pcrVal = chain.pcr ?? (totalCallOI > 0 ? totalPutOI / totalCallOI : null);

    const maxCallRow = rawRows.reduce(
      (a, b) => b.callOI > a.callOI ? b : a,
      rawRows[0] ?? { callOI: 0, strike: 0, putOI: 0, callOIChange: 0, putOIChange: 0 }
    );
    const maxPutRow = rawRows.reduce(
      (a, b) => b.putOI > a.putOI ? b : a,
      rawRows[0] ?? { callOI: 0, strike: 0, putOI: 0, callOIChange: 0, putOIChange: 0 }
    );

    return {
      rows: rawRows,
      atmStrike: atm,
      maxOI,
      totalCallOI,
      totalPutOI,
      pcr: pcrVal,
      maxCallStrike: maxCallRow?.strike ?? null,
      maxPutStrike:  maxPutRow?.strike  ?? null,
    };
  }, [chain, spot, filter]);

  const spotLtp = spot?.ltp ?? null;
  const expiryButtons = expiries.slice(0, 5);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden select-none">

      {/* Header */}
      <div className="flex-none bg-surface-card border-b border-border-default px-2 py-1.5 space-y-1.5">

        {/* Row 1 */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <Selector
            value={symDef.label}
            options={SYMBOLS.map((s) => s.label)}
            onChange={(val) => {
              const idx = SYMBOLS.findIndex((s) => s.label === val);
              setActiveSymbolIdx(idx);
            }}
          />

          <span className="px-2 py-1 text-xs font-medium text-text-muted bg-surface-base border border-border-default rounded">
            {exchange}
          </span>

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

          <button
            onClick={fetchData}
            disabled={loading}
            className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors disabled:opacity-40"
            title="Refresh"
          >
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          </button>
        </div>

        {/* Row 2: spot, PCR, filter */}
        <div className="flex items-center gap-2 flex-wrap">
          {spotLtp != null ? (
            <div className="flex items-center gap-1">
              <span className="text-xs text-text-muted uppercase tracking-wide">Spot</span>
              <span className="font-mono text-sm font-semibold text-text-primary">
                {spotLtp.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
              </span>
            </div>
          ) : (
            <span className="text-xs text-text-muted">Spot: —</span>
          )}

          {pcr != null && (
            <div className="flex items-center gap-1">
              <span className="text-xs text-text-muted uppercase tracking-wide">PCR</span>
              <span className={`font-mono text-xs font-semibold px-1.5 py-0.5 rounded border ${
                Number(pcr) >= 1.2
                  ? "text-profit bg-profit/10 border-profit/30"
                  : Number(pcr) <= 0.8
                    ? "text-loss bg-loss/10 border-loss/30"
                    : "text-warning bg-warning/10 border-warning/30"
              }`}>
                {Number(pcr).toFixed(2)}
                <span className="ml-1 font-normal text-xxs">
                  {Number(pcr) >= 1.2 ? "Bullish" : Number(pcr) <= 0.8 ? "Bearish" : "Neutral"}
                </span>
              </span>
            </div>
          )}

          {maxPutStrike != null && (
            <div className="flex items-center gap-1">
              <span className="text-xxs text-profit/80 bg-profit/10 border border-profit/20 rounded px-1 py-0.5 font-mono">
                S {NUM0.format(maxPutStrike)}
              </span>
            </div>
          )}
          {maxCallStrike != null && (
            <div className="flex items-center gap-1">
              <span className="text-xxs text-loss/80 bg-loss/10 border border-loss/20 rounded px-1 py-0.5 font-mono">
                R {NUM0.format(maxCallStrike)}
              </span>
            </div>
          )}

          <div className="flex-1" />

          <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
            {FILTERS.map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-2 py-0.5 text-xs font-medium transition-colors ${
                  f === filter
                    ? "bg-accent/15 text-accent"
                    : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="flex-none flex items-center gap-2 px-2 py-1 bg-loss/10 border-b border-loss/20 text-loss text-xs">
          <AlertCircle size={11} />
          <span>{error}</span>
        </div>
      )}

      {/* Column header row */}
      <div className="flex-none flex items-center text-xs text-text-muted bg-surface-card border-b border-border-default h-5.5 px-0">
        <div className="flex-1 text-right pr-2 uppercase tracking-wide text-loss/70">
          Call OI
        </div>
        <div className="flex-none w-18 text-center uppercase tracking-wide text-accent/70 border-x border-border-default">
          Strike
        </div>
        <div className="flex-1 text-left pl-2 uppercase tracking-wide text-profit/70">
          Put OI
        </div>
      </div>

      {/* Chart body */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        {!selectedExpiry && !loading ? (
          <div className="h-full flex items-center justify-center text-text-muted text-xs">
            Select an expiry to load OI data
          </div>
        ) : loading && !chain ? (
          <div className="h-full flex items-center justify-center text-text-muted text-xs gap-2">
            <RefreshCw size={13} className="animate-spin" />
            Loading open interest…
          </div>
        ) : rows.length === 0 ? (
          <div className="h-full flex items-center justify-center text-text-muted text-xs">
            {filter !== "All" ? "No strikes match the filter" : "No OI data"}
          </div>
        ) : (
          <div>
            {rows.map(({ strike, callOI, putOI }) => (
              <OIRow
                key={strike}
                strike={strike}
                callOI={callOI}
                putOI={putOI}
                maxOI={maxOI}
                isAtm={strike === atmStrike}
                isMaxCall={strike === maxCallStrike}
                isMaxPut={strike === maxPutStrike}
                spotLtp={strike === atmStrike ? spotLtp : null}
              />
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      {chain && rows.length > 0 && (
        <div className="flex-none bg-surface-card border-t border-border-default px-3 py-1 flex items-center gap-4 text-xs">
          <span className="text-text-muted uppercase tracking-wide">Total</span>
          <span className="text-loss font-mono">CE {fmtOI(totalCallOI)}</span>
          <span className="text-profit font-mono">PE {fmtOI(totalPutOI)}</span>
          {atmStrike != null && (
            <span className="text-text-muted ml-1">
              ATM: <span className="font-mono text-accent">{NUM0.format(atmStrike)}</span>
            </span>
          )}
          {lastRefresh && (
            <div className="flex items-center gap-1 ml-auto text-text-muted">
              <RefreshCw size={9} />
              {lastRefresh.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}
              <span className="ml-1">{isMarketHours() ? "· 5s" : "· 30s"}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
