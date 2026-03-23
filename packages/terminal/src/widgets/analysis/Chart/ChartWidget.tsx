import { useState, useEffect, useRef, useCallback } from "react";
import type { Time } from "lightweight-charts";
import {
  Search,
  X,
  Minus,
  TrendingUp,
  TrendingDown,
  BarChart2,
  Triangle,
  Square,
  Type,
  AlignJustify,
  Move,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
  DropdownMenuCheckboxItem,
  DropdownMenuSeparator,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";
import { searchSymbol, getHistory, getQuotes, getIntervals } from "@/services/api";

// Local modules
import { ChartLegend } from "./ChartLegend";
import type { LegendState } from "./ChartLegend";
import { useChartInit } from "./useChartInit";
import { useDrawingTools } from "./useDrawingTools";
import { useIndicators } from "./useIndicators";
import type { OhlcvBar } from "./indicators";
import type {
  SymbolSearchResult,
  IntervalOption,
  DrawToolType,
  DrawingPoint,
  Drawing,
  IndicatorState,
  IndicatorPeriods,
  IndicatorSeriesRefs,
} from "./types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_SYMBOL = "NIFTY";
const DEFAULT_EXCHANGE = "NSE_INDEX";

const STATIC_INTERVALS: IntervalOption[] = [
  { label: "1m",  value: "1m"  },
  { label: "3m",  value: "3m"  },
  { label: "5m",  value: "5m"  },
  { label: "15m", value: "15m" },
  { label: "30m", value: "30m" },
  { label: "1h",  value: "1h"  },
  { label: "4h",  value: "4h"  },
  { label: "1D",  value: "1D"  },
  { label: "1W",  value: "1W"  },
];

const LOOKBACK_DAYS: Record<string, number> = {
  "1m": 3, "3m": 7, "5m": 10, "15m": 20, "30m": 30,
  "1h": 60, "4h": 120, "1D": 365, "1W": 730,
};

const DEFAULT_INDICATORS: IndicatorState = {
  showEMA20: false, showEMA50: false, showSMA: false, showWMA: false,
  showBB: false, showSupertrend: false, showVWAP: false, showIchimoku: false,
  showPivot: false, showVolume: true,
  showRSI: false, showMACD: false, showStoch: false, showATR: false, showADX: false,
  showWilliamsR: false, showCCI: false, showDEMA: false, showHullMA: false,
  showParabolicSAR: false, showOBV: false, showKeltner: false, showVWMA: false,
};

const DEFAULT_PERIODS: IndicatorPeriods = {
  ema1: 20, ema2: 50, sma: 20, wma: 20,
  bbPeriod: 20, bbMult: 2, stPeriod: 10, stFactor: 3,
  rsi: 14, cci: 20, dema: 20, hull: 20, wr: 14,
  keltner: 20, keltnerMult: 2.0, vwma: 20, atr: 14, adx: 14,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function getStartDate(interval: string): string {
  const d = new Date();
  d.setDate(d.getDate() - (LOOKBACK_DAYS[interval] ?? 30));
  return formatDate(d);
}

function formatPrice(v: number | null | undefined): string {
  if (v == null) return "--";
  return Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatChange(v: number | null): string {
  if (v == null) return "--";
  return `${v >= 0 ? "+" : ""}${Number(v).toFixed(2)}`;
}

function formatChangePct(v: number | null): string {
  if (v == null) return "--";
  return `${v >= 0 ? "+" : ""}${Number(v).toFixed(2)}%`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface SymbolSearchProps { onSelect: (item: SymbolSearchResult) => void }

function SymbolSearch({ onSelect }: SymbolSearchProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SymbolSearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!query.trim() || query.length < 2) { setResults([]); setOpen(false); return; }
    timerRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const raw = await searchSymbol(query.trim());
        const list = Array.isArray(raw) ? raw : ((raw as { data?: SymbolSearchResult[] })?.data ?? []);
        setResults(list.slice(0, 12));
        setOpen(list.length > 0);
        setActiveIdx(-1);
      } catch { setResults([]); setOpen(false); }
      finally { setLoading(false); }
    }, 300);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [query]);

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (dropRef.current && !dropRef.current.contains(e.target as Node) &&
          inputRef.current && !inputRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, []);

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActiveIdx((i) => Math.min(i + 1, results.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActiveIdx((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter" && activeIdx >= 0) { e.preventDefault(); pick(results[activeIdx]); }
    else if (e.key === "Escape") { setOpen(false); }
  }

  function pick(item: SymbolSearchResult) { setQuery(""); setOpen(false); setResults([]); onSelect(item); }
  function clear() { setQuery(""); setOpen(false); setResults([]); inputRef.current?.focus(); }

  return (
    <div className="relative flex items-center">
      <div className="flex items-center gap-1 h-8 bg-surface-card border border-border-default rounded-md px-2 py-1 w-52 focus-within:border-accent transition-colors">
        <Search size={12} className="text-text-muted shrink-0" />
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => results.length > 0 && setOpen(true)}
          placeholder="Search symbol..."
          className="bg-transparent text-sm text-text-primary placeholder-text-muted outline-none w-full font-sans"
          spellCheck={false}
        />
        {loading && <span className="text-text-muted text-xs shrink-0 animate-pulse">...</span>}
        {query && !loading && (
          <button onClick={clear} className="text-text-muted hover:text-text-primary transition-colors">
            <X size={11} />
          </button>
        )}
      </div>
      {open && results.length > 0 && (
        <div ref={dropRef} className="absolute top-full left-0 mt-1 z-50 w-72 bg-surface-card border border-border-default rounded shadow-2xl overflow-hidden">
          {results.map((item, idx) => (
            <button
              key={`${item.symbol}-${item.exchange}-${idx}`}
              onClick={() => pick(item)}
              className={`w-full flex items-center justify-between px-3 py-2 text-left transition-colors ${idx === activeIdx ? "bg-border-default text-text-primary" : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"}`}
            >
              <span className="flex flex-col gap-0.5">
                <span className="text-xs font-mono font-semibold text-text-primary">{item.symbol}</span>
                {item.name && <span className="text-xs text-text-muted truncate max-w-40">{item.name}</span>}
              </span>
              <span className="flex flex-col items-end gap-0.5">
                <span className="text-xs font-mono text-accent">{item.exchange}</span>
                {item.instrument_type && <span className="text-xxs text-text-muted uppercase">{item.instrument_type}</span>}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

interface IntervalPillsProps { intervals: IntervalOption[]; active: string; onSelect: (value: string) => void }

function IntervalPills({ intervals, active, onSelect }: IntervalPillsProps) {
  return (
    <div className="flex items-center gap-0.5">
      {intervals.map((iv) => (
        <button
          key={iv.value}
          onClick={() => onSelect(iv.value)}
          className={`px-2 py-1 text-xs font-mono rounded transition-colors ${active === iv.value ? "bg-accent/15 text-accent border border-accent/40" : "text-text-muted hover:text-text-primary hover:bg-surface-hover"}`}
        >
          {iv.label}
        </button>
      ))}
    </div>
  );
}

interface DrawToolBtnProps {
  toolId: DrawToolType; active: DrawToolType | null;
  onClick: (t: DrawToolType) => void; title: string; children: React.ReactNode;
}

function DrawToolBtn({ toolId, active, onClick, title, children }: DrawToolBtnProps) {
  return (
    <button
      onClick={() => onClick(toolId)}
      title={title}
      className={`flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors ${active === toolId ? "bg-accent/15 text-accent" : "text-text-secondary hover:text-text-primary hover:bg-surface-hover"}`}
    >
      {children}
    </button>
  );
}

interface TextInputOverlayProps { onConfirm: (text: string) => void; onCancel: () => void }

function TextInputOverlay({ onConfirm, onCancel }: TextInputOverlayProps) {
  const [val, setVal] = useState("");
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { ref.current?.focus(); }, []);
  return (
    <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 bg-surface-card border border-border-default rounded px-3 py-2 shadow-2xl">
      <input
        ref={ref}
        value={val}
        onChange={(e) => setVal(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && val.trim()) onConfirm(val.trim());
          if (e.key === "Escape") onCancel();
        }}
        placeholder="Enter annotation text..."
        className="bg-transparent text-xs font-mono text-text-primary outline-none w-48 placeholder-text-muted"
      />
      <button onClick={() => val.trim() && onConfirm(val.trim())} className="text-xs bg-accent text-white px-2 py-0.5 rounded">Place</button>
      <button onClick={onCancel} className="text-xs text-text-muted hover:text-loss px-1"><X size={11} /></button>
    </div>
  );
}

function PeriodInput({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <Input
      type="number" min={2} max={500} value={value}
      className="w-11 h-6 text-xs font-mono text-center px-1 py-0 ml-auto bg-surface-card border-border-default rounded"
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
      onChange={(e) => { const v = parseInt(e.target.value, 10); if (!isNaN(v) && v >= 2 && v <= 500) onChange(v); }}
    />
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function ChartWidget() {
  const [symbol, setSymbol] = useState(DEFAULT_SYMBOL);
  const [exchange, setExchange] = useState(DEFAULT_EXCHANGE);
  const [interval, setInterval] = useState("5m");
  const [intervals, setIntervals] = useState<IntervalOption[]>(STATIC_INTERVALS);

  const [ltp, setLtp] = useState<number | null>(null);
  const [change, setChange] = useState<number | null>(null);
  const [changePct, setChangePct] = useState<number | null>(null);
  const [legend, setLegend] = useState<LegendState | null>(null);

  const [drawMode, setDrawMode] = useState<DrawToolType | null>(null);
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [pendingPoint, setPendingPoint] = useState<DrawingPoint | null>(null);
  const [awaitingText, setAwaitingText] = useState<DrawingPoint | null>(null);

  const [indicators, setIndicators] = useState<IndicatorState>(DEFAULT_INDICATORS);
  const [periods, setPeriods] = useState<IndicatorPeriods>(DEFAULT_PERIODS);

  const barsRef = useRef<OhlcvBar[]>([]);
  const timesRef = useRef<Time[]>([]);

  // Initialise chart (once)
  const { containerRef, chartRef, candleRef, volumeRef, markersPluginRef, indRef } =
    useChartInit(setLegend);

  // Drawing tools
  const { toggleDrawMode, clearAllDrawings, undoLastDrawing } = useDrawingTools({
    chartRef, candleRef, markersPluginRef,
    drawMode, setDrawMode,
    drawings, setDrawings,
    pendingPoint, setPendingPoint,
    setAwaitingText,
  });

  // Indicator series lifecycle
  useIndicators({
    chartRef, candleRef, volumeRef, indRef,
    barsRef, timesRef,
    indicators, periods,
  });

  // Load available intervals from API once
  useEffect(() => {
    getIntervals()
      .then((raw) => {
        if (!raw) return;
        let list: IntervalOption[] = [];
        if (Array.isArray(raw)) {
          list = raw.map((v) => typeof v === "string" ? { label: v, value: v } : (v as IntervalOption));
        } else if ((raw as { intervals?: string[] }).intervals && Array.isArray((raw as { intervals: string[] }).intervals)) {
          list = (raw as { intervals: string[] }).intervals.map((v) =>
            typeof v === "string" ? { label: v, value: v } : { label: String(v), value: String(v) },
          );
        }
        if (list.length > 0) {
          const apiValues = new Set(list.map((x) => x.value));
          const filtered = STATIC_INTERVALS.filter((x) => apiValues.has(x.value));
          if (filtered.length > 0) setIntervals(filtered);
        }
      })
      .catch(() => { /* use static fallback */ });
  }, []);

  // Fetch OHLCV data
  useEffect(() => {
    const candle = candleRef.current;
    const volume = volumeRef.current;
    if (!candle || !volume) return;
    let cancelled = false;

    (async () => {
      try {
        const endDate = formatDate(new Date());
        const startDate = getStartDate(interval);
        const data = await getHistory(symbol, exchange, interval, startDate, endDate);
        if (cancelled || !Array.isArray(data)) return;

        barsRef.current = data as OhlcvBar[];
        const times: Time[] = (data as OhlcvBar[]).map((b) => b.timestamp as unknown as Time);
        timesRef.current = times;

        const candles = (data as OhlcvBar[]).map((b, i) => ({
          time: times[i], open: b.open, high: b.high, low: b.low, close: b.close,
        }));
        const volumes = (data as OhlcvBar[]).map((b, i) => ({
          time: times[i], value: b.volume || 0,
          color: b.close >= b.open ? "rgba(34,197,94,0.3)" : "rgba(239,68,68,0.3)",
        }));

        candle.setData(candles);
        volume.setData(volumes);
        chartRef.current?.timeScale().fitContent();
      } catch { /* API unavailable */ }
    })();

    return () => { cancelled = true; };
  }, [symbol, exchange, interval, candleRef, volumeRef, chartRef]);

  // Fetch quote (LTP / change)
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const q = await getQuotes(symbol, exchange);
        if (cancelled || !q) return;
        const ltpVal = q.ltp ?? null;
        const prevClose = (q as unknown as { prev_close?: number }).prev_close ?? q.close ?? null;
        const chg = ltpVal != null && prevClose != null ? ltpVal - prevClose : null;
        const chgPct = chg != null && prevClose ? (chg / prevClose) * 100 : null;
        if (!cancelled) { setLtp(ltpVal); setChange(chg); setChangePct(chgPct); }
      } catch { /* quote unavailable */ }
    })();
    return () => { cancelled = true; };
  }, [symbol, exchange]);

  // Event handlers
  const handleSymbolSelect = useCallback((item: SymbolSearchResult) => {
    setSymbol(item.symbol);
    setExchange(item.exchange);
    setLtp(null); setChange(null); setChangePct(null); setLegend(null);
    setDrawings([]); setPendingPoint(null);
    const chart = chartRef.current;
    if (chart) {
      const ind = indRef.current;
      (Object.keys(ind) as (keyof IndicatorSeriesRefs)[]).forEach((k) => {
        if (ind[k]) { try { chart.removeSeries(ind[k]!); } catch { /* ignore */ } ind[k] = null; }
      });
    }
  }, [chartRef, indRef]);

  const handleIntervalChange = useCallback((v: string) => { setInterval(v); }, []);

  const handleTextConfirm = useCallback((text: string) => {
    if (!awaitingText) return;
    setDrawings((prev) => [...prev, { kind: "text", id: Math.random().toString(36).slice(2, 10), point: awaitingText, label: text }]);
    setAwaitingText(null);
  }, [awaitingText]);

  const handleTextCancel = useCallback(() => { setAwaitingText(null); }, []);

  const toggleIndicator = useCallback((key: keyof IndicatorState, value: boolean) => {
    setIndicators((prev) => ({ ...prev, [key]: value }));
  }, []);

  // Derived display values
  const isPositive = change == null ? null : change >= 0;
  const changeColor = change == null ? "text-text-secondary" : isPositive ? "text-profit" : "text-loss";
  const activeIndicatorCount = (Object.keys(indicators) as (keyof IndicatorState)[])
    .filter((k) => k !== "showVolume" && indicators[k]).length;
  const drawingCount = drawings.length;
  const twoClickTools: DrawToolType[] = ["trendline", "ray", "fib", "rect"];
  const isTwoClickMode = drawMode !== null && twoClickTools.includes(drawMode);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex flex-col h-full w-full bg-surface-base overflow-hidden">

      {/* Header */}
      <div className="flex items-center justify-between px-2 py-1 bg-surface-base border-b border-border-default shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <SymbolSearch onSelect={handleSymbolSelect} />
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm font-heading font-semibold text-text-primary leading-none whitespace-nowrap">{symbol}</span>
            <span className="text-xs text-text-muted whitespace-nowrap">{exchange}</span>
            {ltp != null && <span className="text-lg font-mono font-bold text-text-primary leading-none whitespace-nowrap">{formatPrice(ltp)}</span>}
            {change != null && (
              <span className={`flex items-center gap-0.5 text-xs font-mono whitespace-nowrap ${changeColor}`}>
                {isPositive ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
                {formatChange(change)} ({formatChangePct(changePct)})
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {legend && <ChartLegend legend={legend} />}
          <IntervalPills intervals={intervals} active={interval} onSelect={handleIntervalChange} />
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-1 px-2 py-0.5 bg-surface-base border-b border-border-default shrink-0 flex-wrap min-h-7">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm" className="h-6 px-2 text-xs font-sans gap-1 text-text-secondary hover:text-text-primary">
              <BarChart2 size={11} />
              Indicators
              {activeIndicatorCount > 0 && (
                <span className="ml-0.5 bg-accent text-white rounded-full min-w-[18px] h-[18px] flex items-center justify-center text-xxs leading-none">{activeIndicatorCount}</span>
              )}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-56 bg-surface-card border-border-default text-text-primary">
            <DropdownMenuLabel className="text-xs text-text-muted uppercase tracking-wider px-2 py-1">Overlays</DropdownMenuLabel>
            <DropdownMenuCheckboxItem checked={indicators.showEMA20} onCheckedChange={(v) => toggleIndicator("showEMA20", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-blue-500 inline-block shrink-0" />EMA
              <PeriodInput value={periods.ema1} onChange={(v) => setPeriods((p) => ({ ...p, ema1: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showEMA50} onCheckedChange={(v) => toggleIndicator("showEMA50", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-amber-500 inline-block shrink-0" />EMA
              <PeriodInput value={periods.ema2} onChange={(v) => setPeriods((p) => ({ ...p, ema2: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showSMA} onCheckedChange={(v) => toggleIndicator("showSMA", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-cyan-500 inline-block shrink-0" />SMA
              <PeriodInput value={periods.sma} onChange={(v) => setPeriods((p) => ({ ...p, sma: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showWMA} onCheckedChange={(v) => toggleIndicator("showWMA", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-lime-500 inline-block shrink-0" />WMA
              <PeriodInput value={periods.wma} onChange={(v) => setPeriods((p) => ({ ...p, wma: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showBB} onCheckedChange={(v) => toggleIndicator("showBB", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-slate-400 inline-block shrink-0" />BB
              <PeriodInput value={periods.bbPeriod} onChange={(v) => setPeriods((p) => ({ ...p, bbPeriod: v }))} />
              <PeriodInput value={periods.bbMult} onChange={(v) => setPeriods((p) => ({ ...p, bbMult: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showSupertrend} onCheckedChange={(v) => toggleIndicator("showSupertrend", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-profit inline-block shrink-0" />Supertrend
              <PeriodInput value={periods.stPeriod} onChange={(v) => setPeriods((p) => ({ ...p, stPeriod: v }))} />
              <PeriodInput value={periods.stFactor} onChange={(v) => setPeriods((p) => ({ ...p, stFactor: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showVWAP} onCheckedChange={(v) => toggleIndicator("showVWAP", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-fuchsia-400 inline-block shrink-0" />VWAP
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showIchimoku} onCheckedChange={(v) => toggleIndicator("showIchimoku", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-profit inline-block shrink-0" />Ichimoku Cloud
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showPivot} onCheckedChange={(v) => toggleIndicator("showPivot", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-slate-400 inline-block shrink-0" />Pivot Points
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showDEMA} onCheckedChange={(v) => toggleIndicator("showDEMA", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-orange-500 inline-block shrink-0" />DEMA
              <PeriodInput value={periods.dema} onChange={(v) => setPeriods((p) => ({ ...p, dema: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showHullMA} onCheckedChange={(v) => toggleIndicator("showHullMA", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-purple-500 inline-block shrink-0" />Hull MA
              <PeriodInput value={periods.hull} onChange={(v) => setPeriods((p) => ({ ...p, hull: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showParabolicSAR} onCheckedChange={(v) => toggleIndicator("showParabolicSAR", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-yellow-400 inline-block shrink-0" />Parabolic SAR
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showKeltner} onCheckedChange={(v) => toggleIndicator("showKeltner", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-orange-500 inline-block shrink-0" />Keltner
              <PeriodInput value={periods.keltner} onChange={(v) => setPeriods((p) => ({ ...p, keltner: v }))} />
              <PeriodInput value={periods.keltnerMult} onChange={(v) => setPeriods((p) => ({ ...p, keltnerMult: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showVWMA} onCheckedChange={(v) => toggleIndicator("showVWMA", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-teal-400 inline-block shrink-0" />VWMA
              <PeriodInput value={periods.vwma} onChange={(v) => setPeriods((p) => ({ ...p, vwma: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuSeparator className="bg-border-default" />
            <DropdownMenuLabel className="text-xs text-text-muted uppercase tracking-wider px-2 py-1">Volume</DropdownMenuLabel>
            <DropdownMenuCheckboxItem checked={indicators.showVolume} onCheckedChange={(v) => toggleIndicator("showVolume", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-slate-500 inline-block shrink-0" />Volume
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showOBV} onCheckedChange={(v) => toggleIndicator("showOBV", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-slate-400 inline-block shrink-0" />OBV
            </DropdownMenuCheckboxItem>
            <DropdownMenuSeparator className="bg-border-default" />
            <DropdownMenuLabel className="text-xs text-text-muted uppercase tracking-wider px-2 py-1">Oscillators</DropdownMenuLabel>
            <DropdownMenuCheckboxItem checked={indicators.showRSI} onCheckedChange={(v) => toggleIndicator("showRSI", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-purple-500 inline-block shrink-0" />RSI
              <PeriodInput value={periods.rsi} onChange={(v) => setPeriods((p) => ({ ...p, rsi: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showMACD} onCheckedChange={(v) => toggleIndicator("showMACD", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-blue-500 inline-block shrink-0" />MACD (12, 26, 9)
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showStoch} onCheckedChange={(v) => toggleIndicator("showStoch", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-orange-500 inline-block shrink-0" />Stochastic (14, 3, 3)
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showATR} onCheckedChange={(v) => toggleIndicator("showATR", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-orange-400 inline-block shrink-0" />ATR
              <PeriodInput value={periods.atr} onChange={(v) => setPeriods((p) => ({ ...p, atr: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showADX} onCheckedChange={(v) => toggleIndicator("showADX", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-amber-400 inline-block shrink-0" />ADX
              <PeriodInput value={periods.adx} onChange={(v) => setPeriods((p) => ({ ...p, adx: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showWilliamsR} onCheckedChange={(v) => toggleIndicator("showWilliamsR", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-pink-400 inline-block shrink-0" />Williams %R
              <PeriodInput value={periods.wr} onChange={(v) => setPeriods((p) => ({ ...p, wr: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showCCI} onCheckedChange={(v) => toggleIndicator("showCCI", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-sky-400 inline-block shrink-0" />CCI
              <PeriodInput value={periods.cci} onChange={(v) => setPeriods((p) => ({ ...p, cci: v }))} />
            </DropdownMenuCheckboxItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <div className="w-px h-4 bg-border-default mx-0.5" />

        <span className="text-xxs text-text-muted uppercase tracking-wider mr-0.5">Draw</span>
        <DrawToolBtn toolId="hline" active={drawMode} onClick={toggleDrawMode} title="Horizontal line — click price level"><Minus size={11} /><span>H-Line</span></DrawToolBtn>
        <DrawToolBtn toolId="vline" active={drawMode} onClick={toggleDrawMode} title="Vertical line — click bar"><AlignJustify size={11} style={{ transform: "rotate(90deg)" }} /><span>V-Line</span></DrawToolBtn>
        <DrawToolBtn toolId="trendline" active={drawMode} onClick={toggleDrawMode} title="Trend line — click two points"><TrendingUp size={11} /><span>Trend</span></DrawToolBtn>
        <DrawToolBtn toolId="ray" active={drawMode} onClick={toggleDrawMode} title="Ray — click origin + direction"><Move size={11} /><span>Ray</span></DrawToolBtn>
        <DrawToolBtn toolId="fib" active={drawMode} onClick={toggleDrawMode} title="Fibonacci retracement — click high + low"><Triangle size={11} /><span>Fib</span></DrawToolBtn>
        <DrawToolBtn toolId="rect" active={drawMode} onClick={toggleDrawMode} title="Rectangle — click two corners"><Square size={11} /><span>Rect</span></DrawToolBtn>
        <DrawToolBtn toolId="text" active={drawMode} onClick={toggleDrawMode} title="Text annotation — click to place"><Type size={11} /><span>Text</span></DrawToolBtn>

        {drawingCount > 0 && (
          <>
            <div className="w-px h-4 bg-border-default mx-0.5" />
            <button onClick={undoLastDrawing} title="Undo last drawing" className="flex items-center gap-1 px-2 py-1 rounded text-xs text-text-secondary hover:text-loss hover:bg-surface-hover transition-colors">
              <X size={10} /><span>Undo</span>
            </button>
            {drawingCount > 1 && (
              <button onClick={clearAllDrawings} title="Clear all drawings" className="flex items-center gap-1 px-2 py-1 rounded text-xs text-text-secondary hover:text-loss hover:bg-surface-hover transition-colors">
                <Trash2 size={10} /><span>Clear</span>
              </button>
            )}
            <span className="text-xxs text-text-muted ml-auto">{drawingCount} drawing{drawingCount !== 1 ? "s" : ""}</span>
          </>
        )}

        {drawMode !== null && !isTwoClickMode && <span className="text-xxs text-accent ml-1 animate-pulse">Click chart to place</span>}
        {isTwoClickMode && pendingPoint === null && <span className="text-xxs text-accent ml-1 animate-pulse">Click first point</span>}
        {isTwoClickMode && pendingPoint !== null && <span className="text-xxs text-accent ml-1 animate-pulse">Click second point</span>}
        {drawMode === "text" && awaitingText !== null && <span className="text-xxs text-accent ml-1 animate-pulse">Type text below</span>}
      </div>

      {/* Chart area */}
      <div className="flex-1 w-full min-h-0 relative">
        <div
          ref={containerRef}
          className="w-full h-full"
          style={{ cursor: drawMode !== null ? "crosshair" : "default" }}
        />
        {awaitingText !== null && (
          <TextInputOverlay onConfirm={handleTextConfirm} onCancel={handleTextCancel} />
        )}
      </div>
    </div>
  );
}
