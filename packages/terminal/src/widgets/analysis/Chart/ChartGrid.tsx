/**
 * ChartGrid — Multi-chart grid widget.
 *
 * Renders 1, 2 (horizontal), 2 (vertical), or 4 independent ChartWidget
 * instances in a CSS-grid layout. Each cell tracks its own symbol, exchange,
 * and interval via local state passed as props into a slimmed-down ChartCell.
 *
 * Layout modes:
 *   "1"  → single full-size chart
 *   "2H" → two charts side by side (2 columns × 1 row)
 *   "2V" → two charts stacked     (1 column × 2 rows)
 *   "4"  → four charts            (2 columns × 2 rows)
 *
 * Registered in widgetFactory.tsx as id "chartgrid".
 */

import { useState, useRef, useEffect, useCallback, memo } from "react";
import { LayoutGrid, Columns2, Rows2, Square } from "lucide-react";
import { isMarketHours } from "@/lib/market";
import { searchSymbol, getHistory, getIntervals } from "@/services/api";
import { Search, X } from "lucide-react";
import { useChartInit } from "./useChartInit";
import { useChartReplay } from "./useChartReplay";
import { ReplayBar } from "./ReplayBar";
import type { OhlcvBar } from "./indicators";
import type { SymbolSearchResult, IntervalOption } from "./types";
import type { Time } from "lightweight-charts";
import { useLightweightChartTheme } from "@/hooks/useChartTheme";
import { safeParse, ohlcvCacheSchema } from "@/lib/safeParse";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type GridLayout = "1" | "2H" | "2V" | "4";

interface CellConfig {
  symbol: string;
  exchange: string;
  interval: string;
}

const DEFAULT_CELLS: CellConfig[] = [
  { symbol: "NIFTY",     exchange: "NSE_INDEX", interval: "5m" },
  { symbol: "BANKNIFTY", exchange: "NSE_INDEX", interval: "5m" },
  { symbol: "FINNIFTY",  exchange: "NSE_INDEX", interval: "5m" },
  { symbol: "MIDCPNIFTY",exchange: "NSE_INDEX", interval: "5m" },
];

const STATIC_INTERVALS: IntervalOption[] = [
  { label: "1m",  value: "1m"  },
  { label: "3m",  value: "3m"  },
  { label: "5m",  value: "5m"  },
  { label: "15m", value: "15m" },
  { label: "30m", value: "30m" },
  { label: "1h",  value: "1h"  },
  { label: "4h",  value: "4h"  },
  { label: "1D",  value: "1D"  },
];

const LOOKBACK_DAYS: Record<string, number> = {
  "1m": 3, "3m": 7, "5m": 10, "15m": 20, "30m": 30,
  "1h": 60, "4h": 120, "1D": 365, "1W": 730,
};

function formatDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function getStartDate(interval: string): string {
  const d = new Date();
  d.setDate(d.getDate() - (LOOKBACK_DAYS[interval] ?? 30));
  return formatDate(d);
}

// ---------------------------------------------------------------------------
// Layout options
// ---------------------------------------------------------------------------

const LAYOUT_OPTIONS: { id: GridLayout; label: string; title: string }[] = [
  { id: "1",  label: "1",  title: "Single chart" },
  { id: "2H", label: "2H", title: "Two charts side by side" },
  { id: "2V", label: "2V", title: "Two charts stacked" },
  { id: "4",  label: "4",  title: "Four charts" },
];

// ---------------------------------------------------------------------------
// Inline symbol search (compact, for cell header)
// ---------------------------------------------------------------------------

interface CellSymbolSearchProps {
  onSelect: (item: SymbolSearchResult) => void;
}

function CellSymbolSearch({ onSelect }: CellSymbolSearchProps) {
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
        setResults(list.slice(0, 8));
        setOpen(list.length > 0);
        setActiveIdx(-1);
      } catch { setResults([]); setOpen(false); }
      finally { setLoading(false); }
    }, 300);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [query]);

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (
        dropRef.current && !dropRef.current.contains(e.target as Node) &&
        inputRef.current && !inputRef.current.contains(e.target as Node)
      ) {
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

  function pick(item: SymbolSearchResult) {
    setQuery(""); setOpen(false); setResults([]);
    onSelect(item);
  }

  return (
    <div className="relative flex items-center">
      <div className="flex items-center gap-1 h-6 bg-surface-card border border-border-default rounded px-1.5 w-36 focus-within:border-accent transition-colors">
        <Search size={10} className="text-text-muted shrink-0" />
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => results.length > 0 && setOpen(true)}
          placeholder="Search…"
          className="bg-transparent text-xs text-text-primary placeholder-text-muted outline-none w-full font-sans"
          spellCheck={false}
          aria-label="Search symbol for this chart cell"
        />
        {loading && <span className="text-text-muted text-xxs shrink-0 animate-pulse">…</span>}
        {query && !loading && (
          <button onClick={() => { setQuery(""); setOpen(false); setResults([]); }} className="text-text-muted hover:text-text-primary transition-colors" aria-label="Clear search">
            <X size={9} />
          </button>
        )}
      </div>
      {open && results.length > 0 && (
        <div
          ref={dropRef}
          className="absolute top-full left-0 mt-0.5 z-50 w-56 bg-surface-card border border-border-default rounded shadow-2xl overflow-hidden"
        >
          {results.map((item, idx) => (
            <button
              key={`${item.symbol}-${item.exchange}-${idx}`}
              onClick={() => pick(item)}
              className={`w-full flex items-center justify-between px-2 py-1.5 text-left transition-colors ${
                idx === activeIdx
                  ? "bg-border-default text-text-primary"
                  : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
              }`}
            >
              <span className="flex flex-col gap-0.5">
                <span className="text-xs font-mono font-semibold text-text-primary">{item.symbol}</span>
                {item.name && <span className="text-xxs text-text-muted truncate max-w-32">{item.name}</span>}
              </span>
              <span className="text-xxs font-mono text-accent">{item.exchange}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Interval pills (compact)
// ---------------------------------------------------------------------------

interface CellIntervalPillsProps {
  intervals: IntervalOption[];
  active: string;
  onSelect: (v: string) => void;
}

function CellIntervalPills({ intervals, active, onSelect }: CellIntervalPillsProps) {
  return (
    <div className="flex items-center gap-0.5">
      {intervals.slice(0, 6).map((iv) => (
        <button
          key={iv.value}
          onClick={() => onSelect(iv.value)}
          className={`px-1.5 py-0.5 text-xxs font-mono rounded transition-colors ${
            active === iv.value
              ? "bg-accent/15 text-accent border border-accent/40"
              : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
          }`}
        >
          {iv.label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chart cell — self-contained chart with header
// ---------------------------------------------------------------------------

interface ChartCellProps {
  config: CellConfig;
  onConfigChange: (next: CellConfig) => void;
  /** When true the cell should not claim a large share of the grid */
  compact?: boolean;
}

function ChartCell({ config, onConfigChange }: ChartCellProps) {
  const [symbol, setSymbol] = useState(config.symbol);
  const [exchange, setExchange] = useState(config.exchange);
  const [interval, setInterval] = useState(config.interval);
  const [intervals, setIntervals] = useState<IntervalOption[]>(STATIC_INTERVALS);

  const barsRef = useRef<OhlcvBar[]>([]);
  const timesRef = useRef<Time[]>([]);
  const isReplayingRef = useRef(false);

  const { containerRef, chartRef, candleRef, volumeRef, indRef } = useChartInit(() => {});

  const chartTheme = useLightweightChartTheme();
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const { candle: _candle, ...chartOptions } = chartTheme;
    chart.applyOptions(chartOptions);
    if (candleRef.current) candleRef.current.applyOptions(chartTheme.candle);
  }, [chartTheme, chartRef, candleRef]);

  const {
    isReplaying, isPlaying, replayIndex, replaySpeed,
    totalBars: replayTotalBars,
    play: replayPlay, pause: replayPause, reset: replayReset,
    seek: replaySeek, exitReplay, enterReplay, setSpeed: replaySetSpeed,
  } = useChartReplay(chartRef, candleRef, barsRef);

  useEffect(() => { isReplayingRef.current = isReplaying; }, [isReplaying]);

  // Restore full bars on replay exit
  useEffect(() => {
    if (!isReplaying && candleRef.current && volumeRef.current && barsRef.current.length > 0) {
      const bars = barsRef.current;
      const times = timesRef.current;
      try {
        candleRef.current.setData(
          bars.map((b, i) => ({ time: times[i], open: b.open, high: b.high, low: b.low, close: b.close })),
        );
        volumeRef.current.setData(
          bars.map((b, i) => ({
            time: times[i], value: b.volume || 0,
            color: b.close >= b.open ? "rgba(34,197,94,0.3)" : "rgba(239,68,68,0.3)",
          })),
        );
        chartRef.current?.timeScale().fitContent();
      } catch { /* ignore */ }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isReplaying]);

  // Load intervals from API once
  useEffect(() => {
    getIntervals()
      .then((raw) => {
        if (!raw) return;
        let list: IntervalOption[] = [];
        if (Array.isArray(raw)) {
          list = raw.map((v) => typeof v === "string" ? { label: v, value: v } : (v as IntervalOption));
        } else if ((raw as { intervals?: string[] }).intervals) {
          list = ((raw as { intervals: string[] }).intervals).map((v) =>
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
    const candleSeries = candle;
    const volumeSeries = volume;
    let cancelled = false;

    function applyBars(data: OhlcvBar[]) {
      if (cancelled || isReplayingRef.current) return;
      const times: Time[] = data.map((b) => b.timestamp as unknown as Time);
      barsRef.current = data;
      timesRef.current = times;
      if (isReplayingRef.current) return;
      try {
        candleSeries.setData(
          data.map((b, i) => ({ time: times[i], open: b.open, high: b.high, low: b.low, close: b.close })),
        );
        volumeSeries.setData(
          data.map((b, i) => ({
            time: times[i], value: b.volume || 0,
            color: b.close >= b.open ? "rgba(34,197,94,0.3)" : "rgba(239,68,68,0.3)",
          })),
        );
        chartRef.current?.timeScale().fitContent();
      } catch { /* ignore */ }
    }

    (async () => {
      const cacheKey = `ft-chart-${symbol}-${exchange}-${interval}`;
      const FIVE_MIN = 5 * 60 * 1000;
      const cached = safeParse(localStorage.getItem(cacheKey), ohlcvCacheSchema);
      if (cached && cached.data.length > 0) {
        applyBars(cached.data);
        if (Date.now() - cached.timestamp < FIVE_MIN && !isMarketHours()) return;
      }

      try {
        const endDate = formatDate(new Date());
        const startDate = getStartDate(interval);
        const data = await getHistory(symbol, exchange, interval, startDate, endDate);
        if (cancelled || !Array.isArray(data) || data.length === 0) return;
        try {
          localStorage.setItem(cacheKey, JSON.stringify({ data, timestamp: Date.now() }));
        } catch { /* quota exceeded */ }
        applyBars(data as OhlcvBar[]);
      } catch { /* API unavailable */ }
    })();

    return () => { cancelled = true; };
  }, [symbol, exchange, interval, candleRef, volumeRef, chartRef]);

  // Sync symbol/exchange changes up to parent
  useEffect(() => {
    onConfigChange({ symbol, exchange, interval });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, exchange, interval]);

  const handleSymbolSelect = useCallback((item: SymbolSearchResult) => {
    setSymbol(item.symbol);
    setExchange(item.exchange);
    // Remove all indicator series when symbol changes
    const chart = chartRef.current;
    if (chart && indRef.current) {
      const ind = indRef.current as unknown as Record<string, Parameters<typeof chart.removeSeries>[0] | null>;
      (Object.keys(ind) as string[]).forEach((k) => {
        if (ind[k]) {
          try { chart.removeSeries(ind[k]!); } catch { /* ignore */ }
          ind[k] = null;
        }
      });
    }
  }, [chartRef, indRef]);

  return (
    <div className="flex flex-col h-full w-full bg-surface-base overflow-hidden border border-border-default rounded-sm">
      {/* Cell header */}
      <div className="flex items-center gap-2 px-2 py-1 bg-surface-base border-b border-border-default shrink-0 flex-wrap min-h-8">
        <CellSymbolSearch onSelect={handleSymbolSelect} />
        <span className="text-xs font-heading font-semibold text-text-primary leading-none whitespace-nowrap">
          {symbol}
        </span>
        <span className="text-xxs text-text-muted">{exchange}</span>
        <div className="flex-1" />
        <CellIntervalPills intervals={intervals} active={interval} onSelect={setInterval} />
      </div>

      {/* Canvas */}
      <div className="flex-1 min-h-0 relative">
        <div ref={containerRef} className="w-full h-full" />
      </div>

      {/* Replay bar */}
      {isReplaying && (
        <ReplayBar
          isPlaying={isPlaying}
          replayIndex={replayIndex}
          totalBars={replayTotalBars}
          replaySpeed={replaySpeed}
          onPlay={replayPlay}
          onPause={replayPause}
          onReset={replayReset}
          onSeek={replaySeek}
          onSetSpeed={replaySetSpeed}
          onExitReplay={exitReplay}
        />
      )}

      {/* Replay toggle button */}
      <div className="flex items-center px-2 py-0.5 bg-surface-base border-t border-border-default shrink-0">
        <button
          onClick={isReplaying ? exitReplay : enterReplay}
          disabled={barsRef.current.length === 0}
          className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-xxs transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
            isReplaying
              ? "bg-accent/15 text-accent border border-accent/40"
              : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
          }`}
          title={isReplaying ? "Exit replay" : "Replay mode"}
        >
          <span>{isReplaying ? "Exit Replay" : "Replay"}</span>
        </button>
      </div>
    </div>
  );
}

const MemoChartCell = memo(ChartCell);

// ---------------------------------------------------------------------------
// Grid layout CSS mapping
// ---------------------------------------------------------------------------

function gridClass(layout: GridLayout): string {
  switch (layout) {
    case "1":  return "grid-cols-1 grid-rows-1";
    case "2H": return "grid-cols-2 grid-rows-1";
    case "2V": return "grid-cols-1 grid-rows-2";
    case "4":  return "grid-cols-2 grid-rows-2";
    default:   return "grid-cols-1 grid-rows-1";
  }
}

function cellCount(layout: GridLayout): number {
  return layout === "1" ? 1 : layout === "4" ? 4 : 2;
}

// ---------------------------------------------------------------------------
// Layout icon helper
// ---------------------------------------------------------------------------

function LayoutIcon({ id }: { id: GridLayout }) {
  if (id === "1")  return <Square size={12} />;
  if (id === "2H") return <Columns2 size={12} />;
  if (id === "2V") return <Rows2 size={12} />;
  return <LayoutGrid size={12} />;
}

// ---------------------------------------------------------------------------
// ChartGrid root
// ---------------------------------------------------------------------------

function ChartGrid() {
  const [layout, setLayout] = useState<GridLayout>("2H");
  const [cells, setCells] = useState<CellConfig[]>([...DEFAULT_CELLS]);

  const handleCellConfigChange = useCallback((index: number, next: CellConfig) => {
    setCells((prev) => {
      const updated = [...prev];
      updated[index] = next;
      return updated;
    });
  }, []);

  const count = cellCount(layout);
  const visibleCells = cells.slice(0, count);

  return (
    <div className="flex flex-col h-full w-full bg-surface-base overflow-hidden">
      {/* Toolbar */}
      <div
        className="flex items-center gap-2 px-3 py-1.5 bg-surface-base border-b border-border-default shrink-0"
        role="toolbar"
        aria-label="Multi chart grid controls"
      >
        <span className="text-xs font-heading text-text-secondary whitespace-nowrap select-none">
          Multi Chart
        </span>
        <div className="w-px h-4 bg-border-default" aria-hidden="true" />

        {/* Layout buttons */}
        <div className="flex items-center gap-0.5" role="group" aria-label="Grid layout">
          {LAYOUT_OPTIONS.map((opt) => (
            <button
              key={opt.id}
              onClick={() => setLayout(opt.id)}
              aria-pressed={layout === opt.id}
              title={opt.title}
              className={`flex items-center gap-1 px-2 py-1 text-xs rounded transition-colors ${
                layout === opt.id
                  ? "bg-accent/15 text-accent border border-accent/40"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
              }`}
            >
              <LayoutIcon id={opt.id} />
              <span className="font-mono">{opt.label}</span>
            </button>
          ))}
        </div>

        <div className="flex-1" />

        <span className="text-xxs text-text-disabled select-none">
          {count} chart{count !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Grid area */}
      <div className={`flex-1 min-h-0 grid gap-px bg-border-default ${gridClass(layout)}`}>
        {visibleCells.map((cell, idx) => (
          <MemoChartCell
            key={idx}
            config={cell}
            onConfigChange={(next) => handleCellConfigChange(idx, next)}
          />
        ))}
      </div>
    </div>
  );
}

export default memo(ChartGrid);
