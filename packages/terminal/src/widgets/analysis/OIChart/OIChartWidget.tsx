/**
 * OIChartWidget — Open Interest Plotly grouped bar chart for FlintTrade terminal.
 *
 * Features:
 *   - Symbol selector (NIFTY / BANKNIFTY / FINNIFTY / MIDCPNIFTY / SENSEX) + Exchange
 *   - Expiry selector (first 5 expiries as buttons)
 *   - Plotly grouped bar chart: Call OI bars (red), Put OI bars (green)
 *   - PCR overlay line on secondary y-axis (per-strike PCR, dotted blue line)
 *   - ATM strike vertical dashed line (yellow)
 *   - Max Pain vertical dashed line (purple)
 *   - PCR badge in header showing overall Put-Call ratio
 *   - Filter buttons: All | OI Increase | OI Decrease
 *   - Support/Resistance labels at max OI strikes
 *   - Auto-refresh: 5s market hours, 30s off-market
 */

import { useState, useEffect, useCallback, useRef, useMemo, lazy, Suspense } from "react";
import { RefreshCw, ChevronDown, AlertCircle } from "lucide-react";
import { getExpiry, getOptionChain, getQuotes, getMaxPain } from "@/services/api";
import type { Quote } from "@/types/api";
import { isMarketHours } from "@/lib/market";
import type { Data, Layout } from "plotly.js";

const PlotlyChart = lazy(() =>
  import("@/components/charts/PlotlyChart").then((m) => ({ default: m.PlotlyChart }))
);

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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

const NUM0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

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
// Main widget
// ---------------------------------------------------------------------------

export default function OIChartWidget() {
  const [activeSymbolIdx, setActiveSymbolIdx] = useState(0);
  const [expiries, setExpiries] = useState<string[]>([]);
  const [selectedExpiry, setSelectedExpiry] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterType>("All");

  const [chain, setChain]     = useState<RawOptionChain | null>(null);
  const [spot, setSpot]       = useState<Quote | null>(null);
  const [maxPainStrike, setMaxPainStrike] = useState<number | null>(null);
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
    setMaxPainStrike(null);
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

  // fetch chain + spot + max pain
  const fetchData = useCallback(async () => {
    if (!selectedExpiry) return;
    setLoading(true);
    setError(null);

    try {
      const [chainRes, spotRes, maxPainRes] = await Promise.allSettled([
        getOptionChain(symDef.label, exchange, selectedExpiry),
        getQuotes(symDef.spotSymbol, symDef.spotExchange),
        getMaxPain(symDef.label, exchange, selectedExpiry),
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

      if (maxPainRes.status === "fulfilled" && maxPainRes.value?.max_pain_strike) {
        setMaxPainStrike(maxPainRes.value.max_pain_strike);
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
  const { rows, atmStrike, totalCallOI, totalPutOI, pcr, maxCallStrike, maxPutStrike } = useMemo(() => {
    if (!chain) {
      return {
        rows: [] as OIRowData[],
        atmStrike: null as number | null,
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
      totalCallOI,
      totalPutOI,
      pcr: pcrVal,
      maxCallStrike: maxCallRow?.strike ?? null,
      maxPutStrike:  maxPutRow?.strike  ?? null,
    };
  }, [chain, spot, filter]);

  // Plotly data construction
  const { plotData, plotLayout } = useMemo<{ plotData: Data[]; plotLayout: Partial<Layout> }>(() => {
    if (rows.length === 0) return { plotData: [], plotLayout: {} };

    const strikes = rows.map((r) => r.strike);
    const ceOI    = rows.map((r) => r.callOI);
    const peOI    = rows.map((r) => r.putOI);

    // Per-strike PCR for overlay line
    const pcrPerStrike = rows.map((r) =>
      r.callOI > 0 ? parseFloat((r.putOI / r.callOI).toFixed(3)) : 0
    );

    const data: Data[] = [
      {
        name: "CE OI",
        type: "bar",
        x: strikes,
        y: ceOI,
        marker: { color: "rgba(239, 68, 68, 0.7)" },
        hovertemplate: "Strike: %{x}<br>CE OI: %{y:,.0f}<extra></extra>",
      },
      {
        name: "PE OI",
        type: "bar",
        x: strikes,
        y: peOI,
        marker: { color: "rgba(34, 197, 94, 0.7)" },
        hovertemplate: "Strike: %{x}<br>PE OI: %{y:,.0f}<extra></extra>",
      },
      {
        name: "PCR",
        type: "scatter",
        mode: "lines",
        x: strikes,
        y: pcrPerStrike,
        yaxis: "y2",
        line: { color: "#60a5fa", width: 2, dash: "dot" },
        hovertemplate: "Strike: %{x}<br>PCR: %{y:.2f}<extra></extra>",
      },
    ];

    // Build shapes and annotations for ATM and Max Pain markers
    const shapes: Partial<Layout>["shapes"] = [];
    const annotations: Partial<Layout>["annotations"] = [];

    if (atmStrike != null) {
      shapes.push({
        type: "line",
        x0: atmStrike, x1: atmStrike,
        y0: 0, y1: 1,
        yref: "paper",
        line: { color: "#fbbf24", width: 2, dash: "dash" },
      });
      annotations.push({
        x: atmStrike, y: 1.04,
        xref: "x", yref: "paper",
        text: "ATM",
        showarrow: false,
        font: { color: "#fbbf24", size: 10 },
      });
    }

    if (maxPainStrike != null) {
      shapes.push({
        type: "line",
        x0: maxPainStrike, x1: maxPainStrike,
        y0: 0, y1: 1,
        yref: "paper",
        line: { color: "#a78bfa", width: 2, dash: "dash" },
      });
      annotations.push({
        x: maxPainStrike, y: 1.04,
        xref: "x", yref: "paper",
        text: "MP",
        showarrow: false,
        font: { color: "#a78bfa", size: 10 },
      });
    }

    const layout: Partial<Layout> = {
      barmode: "group",
      bargap: 0.15,
      bargroupgap: 0.05,
      margin: { t: 24, r: 55, b: 40, l: 55 },
      xaxis: {
        title: { text: "Strike", font: { size: 10 } },
        tickfont: { size: 9 },
        tickangle: -45,
      },
      yaxis: {
        title: { text: "OI", font: { size: 10 } },
        tickfont: { size: 9 },
      },
      yaxis2: {
        title: { text: "PCR", font: { size: 10 } },
        overlaying: "y",
        side: "right",
        tickfont: { size: 9 },
        range: [0, Math.max(3, ...pcrPerStrike) * 1.2],
        showgrid: false,
      },
      legend: {
        orientation: "h",
        yanchor: "bottom",
        y: 1.02,
        xanchor: "right",
        x: 1,
        font: { size: 10 },
      },
      shapes,
      annotations,
    };

    return { plotData: data, plotLayout: layout };
  }, [rows, atmStrike, maxPainStrike]);

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

        {/* Row 2: spot, PCR badge, max pain, support/resistance, filter */}
        <div className="flex items-center gap-2 flex-wrap">
          {spotLtp != null ? (
            <div className="flex items-center gap-1">
              <span className="text-xs text-text-muted uppercase tracking-wide">Spot</span>
              <span className="font-mono tabular-nums text-sm font-semibold text-text-primary">
                {spotLtp.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
              </span>
            </div>
          ) : (
            <span className="text-xs text-text-muted">Spot: —</span>
          )}

          {pcr != null && (
            <span className={`px-2 py-0.5 rounded text-xxs font-medium border font-mono ${
              Number(pcr) >= 1.2
                ? "text-profit bg-profit/10 border-profit/30"
                : Number(pcr) <= 0.8
                  ? "text-loss bg-loss/10 border-loss/30"
                  : "text-warning bg-warning/10 border-warning/30"
            }`}>
              PCR: {Number(pcr).toFixed(2)}
              <span className="ml-1 font-normal opacity-70 text-xxs">
                {Number(pcr) >= 1.2 ? "Bullish" : Number(pcr) <= 0.8 ? "Bearish" : "Neutral"}
              </span>
            </span>
          )}

          {maxPainStrike != null && (
            <span className="px-2 py-0.5 rounded text-xxs font-medium bg-purple-500/20 text-purple-400 border border-purple-500/30 font-mono">
              Max Pain: {NUM0.format(maxPainStrike)}
            </span>
          )}

          {maxPutStrike != null && (
            <span className="text-xxs text-profit/80 bg-profit/10 border border-profit/20 rounded px-1 py-0.5 font-mono">
              S {NUM0.format(maxPutStrike)}
            </span>
          )}
          {maxCallStrike != null && (
            <span className="text-xxs text-loss/80 bg-loss/10 border border-loss/20 rounded px-1 py-0.5 font-mono">
              R {NUM0.format(maxCallStrike)}
            </span>
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

      {/* Chart body */}
      <div className="flex-1 min-h-0 overflow-hidden">
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
          <Suspense fallback={
            <div className="h-full flex items-center justify-center text-text-muted text-xs gap-2">
              <RefreshCw size={13} className="animate-spin" />
              Loading chart…
            </div>
          }>
            <PlotlyChart
              data={plotData}
              layout={plotLayout}
              config={{ displayModeBar: false, responsive: true }}
              style={{ width: "100%", height: "100%" }}
            />
          </Suspense>
        )}
      </div>

      {/* Footer */}
      {chain && rows.length > 0 && (
        <div className="flex-none bg-surface-card border-t border-border-default px-3 py-1 flex items-center gap-4 text-xs">
          <span className="text-text-muted uppercase tracking-wide">Total</span>
          <span className="text-loss font-mono tabular-nums">CE {totalCallOI > 0 ? (totalCallOI >= 1e7 ? `${(totalCallOI / 1e7).toFixed(1)}Cr` : totalCallOI >= 1e5 ? `${(totalCallOI / 1e5).toFixed(1)}L` : NUM0.format(totalCallOI)) : "0"}</span>
          <span className="text-profit font-mono tabular-nums">PE {totalPutOI > 0 ? (totalPutOI >= 1e7 ? `${(totalPutOI / 1e7).toFixed(1)}Cr` : totalPutOI >= 1e5 ? `${(totalPutOI / 1e5).toFixed(1)}L` : NUM0.format(totalPutOI)) : "0"}</span>
          {atmStrike != null && (
            <span className="text-text-muted ml-1">
              ATM: <span className="font-mono text-warning">{NUM0.format(atmStrike)}</span>
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
