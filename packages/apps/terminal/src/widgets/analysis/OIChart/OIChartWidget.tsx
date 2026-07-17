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

import { useState, useEffect, useCallback, useRef, useMemo, lazy, Suspense, memo } from "react";
import { RefreshCw, ChevronDown, AlertCircle } from "lucide-react";
import { getExpiry, getOptionChain, getQuotes, getMaxPain } from "@/services/api";
import type { Quote } from "@/types/api";
import { isMarketHours } from "@/lib/market";
import { useModeStore } from "@/stores/modeStore";
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

interface RawOptionChainEntry {
  strike?: number;
  ce?: RawOptionRow | null;
  pe?: RawOptionRow | null;
}

interface RawOptionChain {
  chain?: RawOptionChainEntry[];
  calls?: RawOptionRow[];
  puts?: RawOptionRow[];
  atm_strike?: number;
  underlying_ltp?: number;
  pcr?: number | null;
}

interface OIRowData {
  strike: number;
  callOI: number | null;
  putOI: number | null;
  callOIChange: number | null;
  putOIChange: number | null;
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

function optionOI(row: RawOptionRow | null | undefined): number | null {
  const raw = row?.oi ?? row?.open_interest;
  if (typeof raw !== "number" || !Number.isFinite(raw) || !Number.isInteger(raw) || raw < 0) return null;
  return raw;
}

function positiveFiniteNumber(value: unknown): number | null {
  if (typeof value !== "number" && typeof value !== "string") return null;
  if (typeof value === "string" && value.trim() === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

export function getOIChange(current: number, previous: number | undefined): number | null {
  return Number.isFinite(current) && previous !== undefined && Number.isFinite(previous)
    ? current - previous
    : null;
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

function optionLegWithStrike(row: RawOptionRow | null | undefined, strike: unknown): RawOptionRow | null {
  if (!row) return null;
  const strikeValue = positiveFiniteNumber(row.strike_price ?? row.strike ?? strike);
  if (strikeValue === null) return null;
  return { ...row, strike: strikeValue, strike_price: strikeValue };
}

function chainCalls(chain: RawOptionChain): RawOptionRow[] {
  if (chain.chain?.length) {
    return chain.chain.flatMap((entry) => {
      const row = optionLegWithStrike(entry.ce, entry.strike);
      return row ? [row] : [];
    });
  }
  return (chain.calls ?? []).flatMap((row) => {
    const normalised = optionLegWithStrike(row, undefined);
    return normalised ? [normalised] : [];
  });
}

function chainPuts(chain: RawOptionChain): RawOptionRow[] {
  if (chain.chain?.length) {
    return chain.chain.flatMap((entry) => {
      const row = optionLegWithStrike(entry.pe, entry.strike);
      return row ? [row] : [];
    });
  }
  return (chain.puts ?? []).flatMap((row) => {
    const normalised = optionLegWithStrike(row, undefined);
    return normalised ? [normalised] : [];
  });
}

function chainHasPositiveOI(chain: RawOptionChain): boolean {
  return [...chainCalls(chain), ...chainPuts(chain)].some((row) => {
    const oi = optionOI(row);
    return oi !== null && oi > 0;
  });
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

function OIChartWidget() {
  const isExplore = useModeStore((s) => s.mode === "explore");
  const [activeSymbolIdx, setActiveSymbolIdx] = useState(0);
  const [expiries, setExpiries] = useState<string[]>([]);
  const [selectedExpiryValue, setSelectedExpiry] = useState<string | null>(null);
  const [expiryIdentity, setExpiryIdentity] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterType>("All");

  const [chain, setChain]     = useState<RawOptionChain | null>(null);
  const [spot, setSpot]       = useState<Quote | null>(null);
  const [maxPainStrike, setMaxPainStrike] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [previousOI, setPreviousOI] = useState<Record<string, number>>({});

  const prevOIRef = useRef<Record<string, number>>({});
  const prevOIKeyRef = useRef<string | null>(null);
  const fetchRequestRef = useRef(0);
  const inFlightRequestKeysRef = useRef(new Map<string, number>());
  const maxPainRequestRef = useRef(0);
  const maxPainInFlightRequestKeysRef = useRef(new Map<string, number>());

  const symDef   = SYMBOLS[activeSymbolIdx];
  const exchange = symDef.exchange;
  const identityKey = `${symDef.label}:${exchange}`;
  const currentExpiries = expiryIdentity === identityKey ? expiries : [];
  const expiryCandidate = typeof selectedExpiryValue === "string" ? selectedExpiryValue.trim() : "";
  const selectedExpiry = currentExpiries.includes(expiryCandidate) ? expiryCandidate : null;
  const requestKey = `${identityKey}:${selectedExpiry ?? ""}`;
  const activeRequestKeyRef = useRef(requestKey);
  activeRequestKeyRef.current = requestKey;

  useEffect(() => {
    fetchRequestRef.current += 1;
    maxPainRequestRef.current += 1;
    setChain(null);
    setSpot(null);
    setMaxPainStrike(null);
    setLoading(false);
    setError(null);
    setLastRefresh(null);
    setPreviousOI({});
    prevOIRef.current = {};
    prevOIKeyRef.current = null;
  }, [requestKey]);

  // fetch expiries
  useEffect(() => {
    fetchRequestRef.current += 1;
    setExpiries([]);
    setSelectedExpiry(null);
    setExpiryIdentity(null);
    setChain(null);
    setSpot(null);
    setMaxPainStrike(null);
    setLoading(false);
    setError(null);
    setLastRefresh(null);
    setPreviousOI({});
    prevOIRef.current = {};
    prevOIKeyRef.current = null;

    let cancelled = false;
    (async () => {
      try {
        const data = await getExpiry(symDef.label, exchange);
        if (cancelled) return;
        const rawList = Array.isArray(data)
          ? data
          : ((data as { expiry?: unknown[] })?.expiry ?? []);
        const list = rawList.flatMap((value) => {
          if (typeof value !== "string") return [];
          const expiry = value.trim();
          return expiry ? [expiry] : [];
        });
        setExpiries(list);
        setExpiryIdentity(identityKey);
        setSelectedExpiry(list[0] ?? null);
      } catch (e) {
        if (!cancelled) setError(`Expiry load failed: ${(e as Error).message}`);
      }
    })();

    return () => { cancelled = true; };
  }, [activeSymbolIdx, identityKey, symDef.label, exchange]);

  // Fetch chain and spot at the market-data cadence.
  const fetchData = useCallback(async () => {
    if (!selectedExpiry) return;
    const fetchKey = `${symDef.label}:${exchange}:${selectedExpiry}`;
    const inFlightRequestId = inFlightRequestKeysRef.current.get(fetchKey);
    if (inFlightRequestId === fetchRequestRef.current) return;
    const requestId = ++fetchRequestRef.current;
    inFlightRequestKeysRef.current.set(fetchKey, requestId);
    setLoading(true);
    setError(null);

    try {
      const [chainRes, spotRes] = await Promise.allSettled([
        getOptionChain(symDef.label, exchange, selectedExpiry),
        getQuotes(symDef.spotSymbol, symDef.spotExchange),
      ]);

      if (
        requestId !== fetchRequestRef.current
        || fetchKey !== activeRequestKeyRef.current
      ) return;

      if (chainRes.status === "fulfilled") {
        const newChain = chainRes.value as unknown as RawOptionChain;
        const snapshot: Record<string, number> = {};
        chainCalls(newChain).forEach((c) => {
          const k = `${c.strike_price ?? c.strike}_CE`;
          const oi = optionOI(c);
          if (oi !== null) snapshot[k] = oi;
        });
        chainPuts(newChain).forEach((p) => {
          const k = `${p.strike_price ?? p.strike}_PE`;
          const oi = optionOI(p);
          if (oi !== null) snapshot[k] = oi;
        });
        const snapshotKey = `${symDef.label}:${exchange}:${selectedExpiry}`;
        setPreviousOI(prevOIKeyRef.current === snapshotKey ? prevOIRef.current : {});
        prevOIRef.current = snapshot;
        prevOIKeyRef.current = snapshotKey;
        setChain(newChain);
      } else {
        setChain(null);
        setError(`Chain error: ${(chainRes.reason as Error)?.message}`);
      }

      if (spotRes.status === "fulfilled") {
        setSpot(spotRes.value);
      } else {
        setSpot(null);
      }

    } finally {
      if (inFlightRequestKeysRef.current.get(fetchKey) === requestId) {
        inFlightRequestKeysRef.current.delete(fetchKey);
      }
      if (
        requestId === fetchRequestRef.current
        && fetchKey === activeRequestKeyRef.current
      ) {
        setLoading(false);
        setLastRefresh(new Date());
      }
    }
  }, [selectedExpiry, symDef.label, symDef.spotExchange, symDef.spotSymbol, exchange]);

  // auto-refresh
  useEffect(() => {
    if (!selectedExpiry) return;
    void fetchData();
    const interval = isMarketHours() ? 5000 : 30000;
    const id = setInterval(() => void fetchData(), interval);
    return () => {
      clearInterval(id);
      fetchRequestRef.current += 1;
    };
  }, [fetchData]);

  // Max Pain is intentionally independent of the faster chain loop.
  const fetchMaxPain = useCallback(async () => {
    if (!selectedExpiry) return;
    const fetchKey = `${symDef.label}:${exchange}:${selectedExpiry}`;
    const inFlightRequestId = maxPainInFlightRequestKeysRef.current.get(fetchKey);
    if (inFlightRequestId === maxPainRequestRef.current) return;

    const requestId = ++maxPainRequestRef.current;
    maxPainInFlightRequestKeysRef.current.set(fetchKey, requestId);
    setMaxPainStrike(null);
    try {
      const data = await getMaxPain(symDef.label, exchange, selectedExpiry);
      if (requestId !== maxPainRequestRef.current || fetchKey !== activeRequestKeyRef.current) return;
      const strike = data.is_sample_data === false
        && typeof data.max_pain_strike === "number"
        && Number.isFinite(data.max_pain_strike)
        && data.max_pain_strike > 0
        ? data.max_pain_strike
        : null;
      setMaxPainStrike(strike);
    } catch {
      if (requestId === maxPainRequestRef.current && fetchKey === activeRequestKeyRef.current) {
        setMaxPainStrike(null);
      }
    } finally {
      if (maxPainInFlightRequestKeysRef.current.get(fetchKey) === requestId) {
        maxPainInFlightRequestKeysRef.current.delete(fetchKey);
      }
    }
  }, [selectedExpiry, symDef.label, exchange]);

  useEffect(() => {
    if (!selectedExpiry) return;
    void fetchMaxPain();
    const id = setInterval(() => void fetchMaxPain(), 60_000);
    return () => {
      clearInterval(id);
      maxPainRequestRef.current += 1;
    };
  }, [fetchMaxPain, selectedExpiry]);

  // computed strike rows
  const { rows, atmStrike, totalCallOI, totalPutOI, pcr, maxCallStrike, maxPutStrike } = useMemo(() => {
    if (!chain) {
      return {
        rows: [] as OIRowData[],
        atmStrike: null as number | null,
        totalCallOI: null as number | null,
        totalPutOI: null as number | null,
        pcr: null as number | null,
        maxCallStrike: null as number | null,
        maxPutStrike: null as number | null,
      };
    }

    const callMap: Record<number, RawOptionRow> = {};
    const putMap:  Record<number, RawOptionRow> = {};

    chainCalls(chain).forEach((call) => {
      const strike = positiveFiniteNumber(call.strike_price ?? call.strike);
      if (strike !== null) callMap[strike] = call;
    });
    chainPuts(chain).forEach((put) => {
      const strike = positiveFiniteNumber(put.strike_price ?? put.strike);
      if (strike !== null) putMap[strike] = put;
    });

    const allStrikes = Array.from(
      new Set([...Object.keys(callMap).map(Number), ...Object.keys(putMap).map(Number)])
    ).sort((a, b) => a - b);

    const spotLtp = positiveFiniteNumber(spot?.ltp)
      ?? positiveFiniteNumber(chain.underlying_ltp);
    const atm = spotLtp !== null && allStrikes.length > 0
      ? allStrikes.reduce((prev, cur) => (
          Math.abs(cur - spotLtp) < Math.abs(prev - spotLtp) ? cur : prev
        ))
      : null;

    const atmIdx = allStrikes.indexOf(atm ?? 0);
    const lo = Math.max(0, atmIdx - STRIKES_AROUND_ATM);
    const hi = Math.min(allStrikes.length - 1, atmIdx + STRIKES_AROUND_ATM);
    const visible = allStrikes.slice(lo, hi + 1);

    const visibleRows: OIRowData[] = visible.map((s) => {
      const callOIValue = optionOI(callMap[s]);
      const putOIValue = optionOI(putMap[s]);
      return {
        strike: s,
        callOI: callOIValue,
        putOI: putOIValue,
        callOIChange: callOIValue === null ? null : getOIChange(callOIValue, previousOI[`${s}_CE`]),
        putOIChange: putOIValue === null ? null : getOIChange(putOIValue, previousOI[`${s}_PE`]),
      };
    });
    let rawRows = visibleRows;

    if (filter === "OI Increase") {
      rawRows = rawRows.filter((r) => (
        (r.callOIChange !== null && r.callOIChange > 0)
        || (r.putOIChange !== null && r.putOIChange > 0)
      ));
    } else if (filter === "OI Decrease") {
      rawRows = rawRows.filter((r) => (
        (r.callOIChange !== null && r.callOIChange < 0)
        || (r.putOIChange !== null && r.putOIChange < 0)
      ));
    }

    const hasCompleteCallOI = rawRows.length > 0 && rawRows.every((row) => row.callOI !== null);
    const hasCompletePutOI = rawRows.length > 0 && rawRows.every((row) => row.putOI !== null);
    const totalCallOI = hasCompleteCallOI
      ? rawRows.reduce((sum, row) => sum + row.callOI!, 0)
      : null;
    const totalPutOI = hasCompletePutOI
      ? rawRows.reduce((sum, row) => sum + row.putOI!, 0)
      : null;
    const pcrVal = totalCallOI !== null && totalCallOI > 0 && totalPutOI !== null
      ? totalPutOI / totalCallOI
      : null;

    const maxCallRow = hasCompleteCallOI && rawRows.length > 0
      ? rawRows.reduce((a, b) => b.callOI! > a.callOI! ? b : a)
      : null;
    const maxPutRow = hasCompletePutOI && rawRows.length > 0
      ? rawRows.reduce((a, b) => b.putOI! > a.putOI! ? b : a)
      : null;

    return {
      rows: rawRows,
      atmStrike: atm,
      totalCallOI,
      totalPutOI,
      pcr: pcrVal,
      maxCallStrike: maxCallRow !== null && maxCallRow.callOI! > 0 ? maxCallRow.strike : null,
      maxPutStrike: maxPutRow !== null && maxPutRow.putOI! > 0 ? maxPutRow.strike : null,
    };
  }, [chain, spot, filter, previousOI]);

  const visibleMaxPainStrike = chain !== null
    && !loading
    && !error
    && chainHasPositiveOI(chain)
    ? maxPainStrike
    : null;

  // Plotly data construction
  const { plotData, plotLayout } = useMemo<{ plotData: Data[]; plotLayout: Partial<Layout> }>(() => {
    if (rows.length === 0) return { plotData: [], plotLayout: {} };

    const strikes = rows.map((r) => r.strike);
    const ceOI    = rows.map((r) => r.callOI);
    const peOI    = rows.map((r) => r.putOI);

    // Per-strike PCR for overlay line
    const pcrPerStrike = rows.map((r) =>
      r.callOI !== null && r.putOI !== null && r.callOI > 0
        ? parseFloat((r.putOI / r.callOI).toFixed(3))
        : null
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

    if (visibleMaxPainStrike != null) {
      shapes.push({
        type: "line",
        x0: visibleMaxPainStrike, x1: visibleMaxPainStrike,
        y0: 0, y1: 1,
        yref: "paper",
        line: { color: "#a78bfa", width: 2, dash: "dash" },
      });
      annotations.push({
        x: visibleMaxPainStrike, y: 1.04,
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
        range: [0, Math.max(3, ...pcrPerStrike.filter((value): value is number => value !== null)) * 1.2],
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
  }, [rows, atmStrike, visibleMaxPainStrike]);

  const spotLtp = positiveFiniteNumber(spot?.ltp);
  const expiryButtons = currentExpiries.slice(0, 5);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden select-none">

      {/* Header */}
      <div className="flex-none bg-surface-card border-b border-border-default px-2 py-1.5 space-y-1.5">

        {/* Row 1 */}
        <div className="flex items-center gap-1.5 flex-wrap">
          {isExplore && (
            <span
              className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
              role="status"
              aria-label="Showing demo data, not live open interest"
              title="Demo data — fabricated sample values, not a live option chain."
            >
              Demo data
            </span>
          )}
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
            disabled={loading || !selectedExpiry}
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

          {visibleMaxPainStrike != null && (
            <span className="px-2 py-0.5 rounded text-xxs font-medium bg-purple-500/20 text-purple-400 border border-purple-500/30 font-mono">
              Max Pain: {NUM0.format(visibleMaxPainStrike)}
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
            <div role="status" className="h-full flex items-center justify-center text-text-muted text-xs gap-2">
              <RefreshCw size={13} className="animate-spin" aria-hidden="true" />
              <span className="sr-only">Loading chart...</span>
              <span aria-hidden="true">Loading chart…</span>
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
          <span className="text-loss font-mono tabular-nums">CE {totalCallOI === null ? "--" : totalCallOI >= 1e7 ? `${(totalCallOI / 1e7).toFixed(1)}Cr` : totalCallOI >= 1e5 ? `${(totalCallOI / 1e5).toFixed(1)}L` : NUM0.format(totalCallOI)}</span>
          <span className="text-profit font-mono tabular-nums">PE {totalPutOI === null ? "--" : totalPutOI >= 1e7 ? `${(totalPutOI / 1e7).toFixed(1)}Cr` : totalPutOI >= 1e5 ? `${(totalPutOI / 1e5).toFixed(1)}L` : NUM0.format(totalPutOI)}</span>
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

export default memo(OIChartWidget);
