import { useState, useEffect, useRef, useCallback } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
} from "lightweight-charts";
import type {
  IChartApi,
  ISeriesApi,
  IPriceLine,
  MouseEventParams,
  CandlestickData,
  HistogramData,
  LineData,
  Time,
} from "lightweight-charts";
import {
  Search,
  X,
  Minus,
  TrendingUp,
  TrendingDown,
  BarChart2,
} from "lucide-react";
import { Button } from "../../../components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
  DropdownMenuCheckboxItem,
  DropdownMenuSeparator,
  DropdownMenuLabel,
} from "../../../components/ui/dropdown-menu";
import { searchSymbol, getHistory, getQuotes, getIntervals } from "../../../services/api";

// --- types -------------------------------------------------------------------

interface FlexLayoutNode {
  getId?: () => string;
}

interface SymbolSearchResult {
  symbol: string;
  exchange: string;
  name?: string;
  instrument_type?: string;
}

interface IntervalOption {
  label: string;
  value: string;
}

interface LegendState {
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  bull: boolean;
}

interface HlineRef {
  _priceLine: IPriceLine;
  _series: ISeriesApi<"Candlestick">;
}

interface OhlcvBar {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface IndicatorState {
  showEMA20: boolean;
  showEMA50: boolean;
  showBB: boolean;
  showSupertrend: boolean;
  showVolume: boolean;
  showRSI: boolean;
  showMACD: boolean;
}

// Indicator series refs bundled together
interface IndicatorSeriesRefs {
  ema20: ISeriesApi<"Line"> | null;
  ema50: ISeriesApi<"Line"> | null;
  bbUpper: ISeriesApi<"Line"> | null;
  bbMiddle: ISeriesApi<"Line"> | null;
  bbLower: ISeriesApi<"Line"> | null;
  stUp: ISeriesApi<"Line"> | null;
  stDown: ISeriesApi<"Line"> | null;
  rsi: ISeriesApi<"Line"> | null;
  macdLine: ISeriesApi<"Line"> | null;
  macdSignal: ISeriesApi<"Line"> | null;
  macdHist: ISeriesApi<"Histogram"> | null;
}

// --- constants ---------------------------------------------------------------

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
  "1m":  3,
  "3m":  7,
  "5m":  10,
  "15m": 20,
  "30m": 30,
  "1h":  60,
  "4h":  120,
  "1D":  365,
  "1W":  730,
};

const CHART_THEME = {
  layout: {
    background: { color: "#0a0a0a" },
    textColor: "#e5e5e5",
    fontFamily: "'JetBrains Mono', ui-monospace, monospace",
    fontSize: 11,
  },
  grid: {
    vertLines: { color: "#1a1a2e" },
    horzLines: { color: "#1a1a2e" },
  },
  crosshair: { mode: 0 },
  rightPriceScale: { borderColor: "#2a2a3e" },
  timeScale: {
    borderColor: "#2a2a3e",
    timeVisible: true,
    secondsVisible: false,
  },
} as const;

const CANDLE_OPTIONS = {
  upColor: "#22c55e",
  downColor: "#ef4444",
  borderUpColor: "#22c55e",
  borderDownColor: "#ef4444",
  wickUpColor: "#22c55e",
  wickDownColor: "#ef4444",
};

const DEFAULT_INDICATORS: IndicatorState = {
  showEMA20: false,
  showEMA50: false,
  showBB: false,
  showSupertrend: false,
  showVolume: true,
  showRSI: false,
  showMACD: false,
};

// --- pure indicator calculations ---------------------------------------------

function calcEMA(closes: number[], period: number): (number | null)[] {
  if (closes.length === 0) return [];
  const k = 2 / (period + 1);
  const result: (number | null)[] = new Array(closes.length).fill(null);
  let ema: number | null = null;

  for (let i = 0; i < closes.length; i++) {
    if (ema === null) {
      if (i >= period - 1) {
        // seed with SMA
        let sum = 0;
        for (let j = i - period + 1; j <= i; j++) sum += closes[j];
        ema = sum / period;
        result[i] = ema;
      }
    } else {
      ema = closes[i] * k + ema * (1 - k);
      result[i] = ema;
    }
  }
  return result;
}

interface BBResult {
  upper: (number | null)[];
  middle: (number | null)[];
  lower: (number | null)[];
}

function calcBollingerBands(closes: number[], period = 20, mult = 2): BBResult {
  const upper: (number | null)[] = new Array(closes.length).fill(null);
  const middle: (number | null)[] = new Array(closes.length).fill(null);
  const lower: (number | null)[] = new Array(closes.length).fill(null);

  for (let i = period - 1; i < closes.length; i++) {
    const slice = closes.slice(i - period + 1, i + 1);
    const sma = slice.reduce((a, b) => a + b, 0) / period;
    const variance = slice.reduce((a, b) => a + (b - sma) ** 2, 0) / period;
    const sd = Math.sqrt(variance);
    middle[i] = sma;
    upper[i] = sma + mult * sd;
    lower[i] = sma - mult * sd;
  }
  return { upper, middle, lower };
}

interface SupertrendResult {
  up: (number | null)[];
  down: (number | null)[];
  direction: (1 | -1 | null)[];
}

function calcSupertrend(
  highs: number[],
  lows: number[],
  closes: number[],
  period = 10,
  factor = 3,
): SupertrendResult {
  const n = closes.length;
  const up: (number | null)[] = new Array(n).fill(null);
  const down: (number | null)[] = new Array(n).fill(null);
  const direction: (1 | -1 | null)[] = new Array(n).fill(null);

  // ATR (Wilder's smoothing)
  const tr: number[] = new Array(n).fill(0);
  for (let i = 1; i < n; i++) {
    tr[i] = Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i - 1]),
      Math.abs(lows[i] - closes[i - 1]),
    );
  }
  tr[0] = highs[0] - lows[0];

  const atr: (number | null)[] = new Array(n).fill(null);
  // seed
  if (n >= period) {
    let sum = 0;
    for (let i = 0; i < period; i++) sum += tr[i];
    atr[period - 1] = sum / period;
    for (let i = period; i < n; i++) {
      const prev = atr[i - 1]!;
      atr[i] = (prev * (period - 1) + tr[i]) / period;
    }
  }

  let prevUp = 0;
  let prevDown = 0;
  let prevDir: 1 | -1 = 1;

  for (let i = period - 1; i < n; i++) {
    const a = atr[i];
    if (a === null) continue;
    const hl2 = (highs[i] + lows[i]) / 2;
    const basicUp = hl2 - factor * a;
    const basicDown = hl2 + factor * a;

    const finalUp = (i === period - 1)
      ? basicUp
      : basicUp > prevUp || closes[i - 1] < prevUp ? basicUp : prevUp;

    const finalDown = (i === period - 1)
      ? basicDown
      : basicDown < prevDown || closes[i - 1] > prevDown ? basicDown : prevDown;

    let dir: 1 | -1;
    if (i === period - 1) {
      dir = 1;
    } else if (prevDir === -1 && closes[i] > prevDown) {
      dir = 1;
    } else if (prevDir === 1 && closes[i] < prevUp) {
      dir = -1;
    } else {
      dir = prevDir;
    }

    up[i] = dir === 1 ? finalUp : null;
    down[i] = dir === -1 ? finalDown : null;
    direction[i] = dir;

    prevUp = finalUp;
    prevDown = finalDown;
    prevDir = dir;
  }

  return { up, down, direction };
}

interface RSIResult {
  values: (number | null)[];
}

function calcRSI(closes: number[], period = 14): RSIResult {
  const n = closes.length;
  const values: (number | null)[] = new Array(n).fill(null);
  if (n < period + 1) return { values };

  let avgGain = 0;
  let avgLoss = 0;

  for (let i = 1; i <= period; i++) {
    const diff = closes[i] - closes[i - 1];
    if (diff > 0) avgGain += diff;
    else avgLoss += -diff;
  }
  avgGain /= period;
  avgLoss /= period;

  const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
  values[period] = 100 - 100 / (1 + rs);

  for (let i = period + 1; i < n; i++) {
    const diff = closes[i] - closes[i - 1];
    const gain = diff > 0 ? diff : 0;
    const loss = diff < 0 ? -diff : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    const rs2 = avgLoss === 0 ? 100 : avgGain / avgLoss;
    values[i] = 100 - 100 / (1 + rs2);
  }

  return { values };
}

interface MACDResult {
  macd: (number | null)[];
  signal: (number | null)[];
  hist: (number | null)[];
}

function calcMACD(
  closes: number[],
  fast = 12,
  slow = 26,
  signal = 9,
): MACDResult {
  const fastEma = calcEMA(closes, fast);
  const slowEma = calcEMA(closes, slow);
  const n = closes.length;

  const macd: (number | null)[] = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    if (fastEma[i] !== null && slowEma[i] !== null) {
      macd[i] = fastEma[i]! - slowEma[i]!;
    }
  }

  // Signal line = EMA of MACD values (only non-null)
  // Build a compact array of MACD values for EMA, mapping back to original indices
  const macdNonNull: number[] = [];
  const macdIndices: number[] = [];
  for (let i = 0; i < n; i++) {
    if (macd[i] !== null) {
      macdNonNull.push(macd[i]!);
      macdIndices.push(i);
    }
  }

  const sigEma = calcEMA(macdNonNull, signal);
  const sigFull: (number | null)[] = new Array(n).fill(null);
  for (let j = 0; j < macdIndices.length; j++) {
    sigFull[macdIndices[j]] = sigEma[j];
  }

  const hist: (number | null)[] = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    if (macd[i] !== null && sigFull[i] !== null) {
      hist[i] = macd[i]! - sigFull[i]!;
    }
  }

  return { macd, signal: sigFull, hist };
}

// Build LineData array from parallel arrays of time and values
function buildLineData(
  times: Time[],
  values: (number | null)[],
): LineData[] {
  const out: LineData[] = [];
  for (let i = 0; i < times.length; i++) {
    if (values[i] !== null) {
      out.push({ time: times[i], value: values[i]! });
    }
  }
  return out;
}

// Build HistogramData array
function buildHistData(
  times: Time[],
  values: (number | null)[],
): HistogramData[] {
  const out: HistogramData[] = [];
  for (let i = 0; i < times.length; i++) {
    if (values[i] !== null) {
      const v = values[i]!;
      out.push({
        time: times[i],
        value: v,
        color: v >= 0 ? "rgba(34,197,94,0.6)" : "rgba(239,68,68,0.6)",
      });
    }
  }
  return out;
}

// --- helpers -----------------------------------------------------------------

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
  return Number(v).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatChange(v: number | null): string {
  if (v == null) return "--";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${Number(v).toFixed(2)}`;
}

function formatChangePct(v: number | null): string {
  if (v == null) return "--";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${Number(v).toFixed(2)}%`;
}

function formatVolume(v: number | null): string {
  if (v == null) return "--";
  if (v >= 1_00_00_000) return `${(v / 1_00_00_000).toFixed(2)}Cr`;
  if (v >= 1_00_000) return `${(v / 1_00_000).toFixed(2)}L`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return String(v);
}

// --- sub-components ----------------------------------------------------------

interface SymbolSearchProps {
  onSelect: (item: SymbolSearchResult) => void;
}

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
    if (!query.trim() || query.length < 2) {
      setResults([]);
      setOpen(false);
      return;
    }
    timerRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const raw = await searchSymbol(query.trim());
        const list = Array.isArray(raw)
          ? raw
          : ((raw as { data?: SymbolSearchResult[] })?.data ?? []);
        setResults(list.slice(0, 12));
        setOpen(list.length > 0);
        setActiveIdx(-1);
      } catch {
        setResults([]);
        setOpen(false);
      } finally {
        setLoading(false);
      }
    }, 300);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [query]);

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (
        dropRef.current &&
        !dropRef.current.contains(e.target as Node) &&
        inputRef.current &&
        !inputRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, []);

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && activeIdx >= 0) {
      e.preventDefault();
      pick(results[activeIdx]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  function pick(item: SymbolSearchResult) {
    setQuery("");
    setOpen(false);
    setResults([]);
    onSelect(item);
  }

  function clear() {
    setQuery("");
    setOpen(false);
    setResults([]);
    inputRef.current?.focus();
  }

  return (
    <div className="relative flex items-center">
      <div className="flex items-center gap-1 bg-surface-card border border-border-default rounded px-2 py-1 w-52 focus-within:border-accent transition-colors">
        <Search size={12} className="text-text-muted shrink-0" />
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => results.length > 0 && setOpen(true)}
          placeholder="Search symbol..."
          className="bg-transparent text-[11px] text-text-primary placeholder-text-muted outline-none w-full font-mono"
          spellCheck={false}
        />
        {loading && (
          <span className="text-text-muted text-[10px] shrink-0 animate-pulse">
            ...
          </span>
        )}
        {query && !loading && (
          <button
            onClick={clear}
            className="text-text-muted hover:text-text-primary transition-colors"
          >
            <X size={11} />
          </button>
        )}
      </div>

      {open && results.length > 0 && (
        <div
          ref={dropRef}
          className="absolute top-full left-0 mt-1 z-50 w-72 bg-surface-card border border-border-default rounded shadow-2xl overflow-hidden"
        >
          {results.map((item, idx) => (
            <button
              key={`${item.symbol}-${item.exchange}-${idx}`}
              onClick={() => pick(item)}
              className={`w-full flex items-center justify-between px-3 py-2 text-left transition-colors ${
                idx === activeIdx
                  ? "bg-border-default text-text-primary"
                  : "text-[#a1a1aa] hover:bg-surface-hover hover:text-text-primary"
              }`}
            >
              <span className="flex flex-col gap-0.5">
                <span className="text-[12px] font-mono font-semibold text-text-primary">
                  {item.symbol}
                </span>
                {item.name && (
                  <span className="text-[10px] text-text-muted truncate max-w-40">
                    {item.name}
                  </span>
                )}
              </span>
              <span className="flex flex-col items-end gap-0.5">
                <span className="text-[10px] font-mono text-accent">
                  {item.exchange}
                </span>
                {item.instrument_type && (
                  <span className="text-[9px] text-text-muted uppercase">
                    {item.instrument_type}
                  </span>
                )}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

interface IntervalPillsProps {
  intervals: IntervalOption[];
  active: string;
  onSelect: (value: string) => void;
}

function IntervalPills({ intervals, active, onSelect }: IntervalPillsProps) {
  return (
    <div className="flex items-center gap-0.5">
      {intervals.map((iv) => (
        <button
          key={iv.value}
          onClick={() => onSelect(iv.value)}
          className={`px-2 py-0.5 text-[10px] font-mono rounded transition-colors ${
            active === iv.value
              ? "bg-accent text-white"
              : "text-text-secondary hover:text-text-primary hover:bg-border-default"
          }`}
        >
          {iv.label}
        </button>
      ))}
    </div>
  );
}

// --- main component ----------------------------------------------------------

interface ChartWidgetProps {
  node?: FlexLayoutNode;
}

export default function ChartWidget({ node: _node }: ChartWidgetProps) {
  // symbol / interval state
  const [symbol, setSymbol] = useState(DEFAULT_SYMBOL);
  const [exchange, setExchange] = useState(DEFAULT_EXCHANGE);
  const [interval, setInterval] = useState("5m");
  const [intervals, setIntervals] = useState<IntervalOption[]>(STATIC_INTERVALS);

  // quote state
  const [ltp, setLtp] = useState<number | null>(null);
  const [change, setChange] = useState<number | null>(null);
  const [changePct, setChangePct] = useState<number | null>(null);

  // crosshair OHLCV legend
  const [legend, setLegend] = useState<LegendState | null>(null);

  // drawing tools
  const [drawMode, setDrawMode] = useState<"hline" | null>(null);
  const [hlines, setHlines] = useState<number[]>([]);
  const hlineSeriesRef = useRef<HlineRef[]>([]);

  // indicator toggles
  const [indicators, setIndicators] = useState<IndicatorState>(DEFAULT_INDICATORS);

  // raw OHLCV data store for indicator recalculation
  const barsRef = useRef<OhlcvBar[]>([]);
  const timesRef = useRef<Time[]>([]);

  // chart refs
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const clickHandlerRef = useRef<((param: MouseEventParams) => void) | null>(null);

  // indicator series refs
  const indRef = useRef<IndicatorSeriesRefs>({
    ema20: null,
    ema50: null,
    bbUpper: null,
    bbMiddle: null,
    bbLower: null,
    stUp: null,
    stDown: null,
    rsi: null,
    macdLine: null,
    macdSignal: null,
    macdHist: null,
  });

  // load available intervals from API once
  useEffect(() => {
    getIntervals()
      .then((raw) => {
        if (!raw) return;
        let list: IntervalOption[] = [];
        if (Array.isArray(raw)) {
          list = raw.map((v) =>
            typeof v === "string" ? { label: v, value: v } : (v as IntervalOption),
          );
        } else if (
          (raw as { intervals?: string[] }).intervals &&
          Array.isArray((raw as { intervals: string[] }).intervals)
        ) {
          list = (raw as { intervals: string[] }).intervals.map((v) =>
            typeof v === "string"
              ? { label: v, value: v }
              : { label: String(v), value: String(v) },
          );
        }
        if (list.length > 0) {
          const apiValues = new Set(list.map((x) => x.value));
          const filtered = STATIC_INTERVALS.filter((x) => apiValues.has(x.value));
          if (filtered.length > 0) setIntervals(filtered);
        }
      })
      .catch(() => {
        /* use static fallback */
      });
  }, []);

  // --- chart creation (once) -----------------------------------------------
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      ...CHART_THEME,
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
    });

    const candleSeries = chart.addSeries(CandlestickSeries, CANDLE_OPTIONS);

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
    });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

    chartRef.current = chart;
    candleRef.current = candleSeries;
    volumeRef.current = volumeSeries;

    // Crosshair OHLCV legend
    chart.subscribeCrosshairMove((param: MouseEventParams) => {
      if (!param || !param.time || !candleSeries) {
        setLegend(null);
        return;
      }
      const bar = param.seriesData.get(candleSeries) as CandlestickData | undefined;
      const vol = param.seriesData.get(volumeSeries) as HistogramData | undefined;
      if (bar) {
        setLegend({
          open: bar.open,
          high: bar.high,
          low: bar.low,
          close: bar.close,
          volume: vol?.value ?? null,
          bull: bar.close >= bar.open,
        });
      }
    });

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        chart.applyOptions({ width, height });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
      hlineSeriesRef.current = [];
      indRef.current = {
        ema20: null,
        ema50: null,
        bbUpper: null,
        bbMiddle: null,
        bbLower: null,
        stUp: null,
        stDown: null,
        rsi: null,
        macdLine: null,
        macdSignal: null,
        macdHist: null,
      };
    };
  }, []); // intentionally empty — chart created once

  // Keep drawMode accessible inside the click handler via ref
  const drawModeRef = useRef<"hline" | null>(drawMode);
  useEffect(() => {
    drawModeRef.current = drawMode;
  }, [drawMode]);

  // Re-subscribe chart click handler whenever drawMode changes
  useEffect(() => {
    const chart = chartRef.current;
    const candle = candleRef.current;
    if (!chart || !candle) return;

    if (clickHandlerRef.current) {
      chart.unsubscribeClick(clickHandlerRef.current);
    }

    const handler = (param: MouseEventParams) => {
      if (!param || !param.point || drawModeRef.current !== "hline") return;
      const price = candle.coordinateToPrice(param.point.y);
      if (price == null) return;
      setHlines((prev) => [...prev, price]);
    };
    clickHandlerRef.current = handler;
    chart.subscribeClick(handler);

    return () => {
      chart.unsubscribeClick(handler);
      clickHandlerRef.current = null;
    };
  }, [drawMode]);

  // --- fetch OHLCV data and recompute indicators ---------------------------
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

        const times: Time[] = (data as OhlcvBar[]).map(
          (b) => b.timestamp as unknown as Time,
        );
        timesRef.current = times;

        const candles = (data as OhlcvBar[]).map((b, i) => ({
          time: times[i],
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
        }));
        const volumes = (data as OhlcvBar[]).map((b, i) => ({
          time: times[i],
          value: b.volume || 0,
          color:
            b.close >= b.open
              ? "rgba(34,197,94,0.3)"
              : "rgba(239,68,68,0.3)",
        }));

        candle.setData(candles);
        volume.setData(volumes);
        chartRef.current?.timeScale().fitContent();
      } catch {
        /* API unavailable — keep existing data */
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [symbol, exchange, interval]);

  // --- manage indicator series on the chart --------------------------------
  // Called whenever indicator state or bar data changes.
  // Strategy: add/remove entire series based on toggle, then set data.
  const refreshIndicators = useCallback(() => {
    const chart = chartRef.current;
    if (!chart) return;

    const bars = barsRef.current;
    const times = timesRef.current;
    if (bars.length === 0 || times.length === 0) return;

    const closes = bars.map((b) => b.close);
    const highs = bars.map((b) => b.high);
    const lows = bars.map((b) => b.low);
    const ind = indRef.current;

    // --- EMA 20 ---
    if (indicators.showEMA20) {
      if (!ind.ema20) {
        ind.ema20 = chart.addSeries(LineSeries, {
          color: "#3b82f6",
          lineWidth: 1,
          priceScaleId: "right",
          title: "EMA20",
          lastValueVisible: false,
          priceLineVisible: false,
        });
      }
      const vals = calcEMA(closes, 20);
      ind.ema20.setData(buildLineData(times, vals));
    } else if (ind.ema20) {
      try { chart.removeSeries(ind.ema20); } catch { /* ignore */ }
      ind.ema20 = null;
    }

    // --- EMA 50 ---
    if (indicators.showEMA50) {
      if (!ind.ema50) {
        ind.ema50 = chart.addSeries(LineSeries, {
          color: "#f59e0b",
          lineWidth: 1,
          priceScaleId: "right",
          title: "EMA50",
          lastValueVisible: false,
          priceLineVisible: false,
        });
      }
      const vals = calcEMA(closes, 50);
      ind.ema50.setData(buildLineData(times, vals));
    } else if (ind.ema50) {
      try { chart.removeSeries(ind.ema50); } catch { /* ignore */ }
      ind.ema50 = null;
    }

    // --- Bollinger Bands ---
    if (indicators.showBB) {
      const bb = calcBollingerBands(closes);
      if (!ind.bbUpper) {
        ind.bbUpper = chart.addSeries(LineSeries, {
          color: "#ef4444",
          lineWidth: 1,
          lineStyle: 2, // dashed
          priceScaleId: "right",
          title: "BB Upper",
          lastValueVisible: false,
          priceLineVisible: false,
        });
      }
      if (!ind.bbMiddle) {
        ind.bbMiddle = chart.addSeries(LineSeries, {
          color: "#94a3b8",
          lineWidth: 1,
          lineStyle: 1, // dotted
          priceScaleId: "right",
          title: "BB Mid",
          lastValueVisible: false,
          priceLineVisible: false,
        });
      }
      if (!ind.bbLower) {
        ind.bbLower = chart.addSeries(LineSeries, {
          color: "#22c55e",
          lineWidth: 1,
          lineStyle: 2,
          priceScaleId: "right",
          title: "BB Lower",
          lastValueVisible: false,
          priceLineVisible: false,
        });
      }
      ind.bbUpper.setData(buildLineData(times, bb.upper));
      ind.bbMiddle.setData(buildLineData(times, bb.middle));
      ind.bbLower.setData(buildLineData(times, bb.lower));
    } else {
      for (const key of ["bbUpper", "bbMiddle", "bbLower"] as const) {
        if (ind[key]) {
          try { chart.removeSeries(ind[key]!); } catch { /* ignore */ }
          ind[key] = null;
        }
      }
    }

    // --- Supertrend ---
    if (indicators.showSupertrend) {
      const st = calcSupertrend(highs, lows, closes);
      if (!ind.stUp) {
        ind.stUp = chart.addSeries(LineSeries, {
          color: "#22c55e",
          lineWidth: 2,
          priceScaleId: "right",
          title: "ST Up",
          lastValueVisible: false,
          priceLineVisible: false,
        });
      }
      if (!ind.stDown) {
        ind.stDown = chart.addSeries(LineSeries, {
          color: "#ef4444",
          lineWidth: 2,
          priceScaleId: "right",
          title: "ST Down",
          lastValueVisible: false,
          priceLineVisible: false,
        });
      }
      ind.stUp.setData(buildLineData(times, st.up));
      ind.stDown.setData(buildLineData(times, st.down));
    } else {
      for (const key of ["stUp", "stDown"] as const) {
        if (ind[key]) {
          try { chart.removeSeries(ind[key]!); } catch { /* ignore */ }
          ind[key] = null;
        }
      }
    }

    // --- Volume (already on chart by default; show/hide via opacity) ---
    if (volumeRef.current) {
      volumeRef.current.applyOptions({
        visible: indicators.showVolume,
      });
    }

    // --- RSI ---
    if (indicators.showRSI) {
      if (!ind.rsi) {
        ind.rsi = chart.addSeries(LineSeries, {
          color: "#a855f7",
          lineWidth: 1,
          priceScaleId: "rsi",
          title: "RSI(14)",
          lastValueVisible: true,
          priceLineVisible: false,
        });
        chart.priceScale("rsi").applyOptions({
          scaleMargins: { top: 0.75, bottom: 0.05 },
        });
      }
      const { values } = calcRSI(closes);
      ind.rsi.setData(buildLineData(times, values));
    } else if (ind.rsi) {
      try { chart.removeSeries(ind.rsi); } catch { /* ignore */ }
      ind.rsi = null;
    }

    // --- MACD ---
    if (indicators.showMACD) {
      const macdData = calcMACD(closes);
      if (!ind.macdHist) {
        ind.macdHist = chart.addSeries(HistogramSeries, {
          priceScaleId: "macd",
          title: "MACD Hist",
          lastValueVisible: false,
          priceLineVisible: false,
        });
        chart.priceScale("macd").applyOptions({
          scaleMargins: { top: 0.6, bottom: 0.05 },
        });
      }
      if (!ind.macdLine) {
        ind.macdLine = chart.addSeries(LineSeries, {
          color: "#3b82f6",
          lineWidth: 1,
          priceScaleId: "macd",
          title: "MACD",
          lastValueVisible: false,
          priceLineVisible: false,
        });
      }
      if (!ind.macdSignal) {
        ind.macdSignal = chart.addSeries(LineSeries, {
          color: "#f97316",
          lineWidth: 1,
          priceScaleId: "macd",
          title: "Signal",
          lastValueVisible: false,
          priceLineVisible: false,
        });
      }
      ind.macdHist.setData(buildHistData(times, macdData.hist));
      ind.macdLine.setData(buildLineData(times, macdData.macd));
      ind.macdSignal.setData(buildLineData(times, macdData.signal));
    } else {
      for (const key of ["macdHist", "macdLine", "macdSignal"] as const) {
        if (ind[key]) {
          try { chart.removeSeries(ind[key]!); } catch { /* ignore */ }
          ind[key] = null;
        }
      }
    }
  }, [indicators]);

  // Refresh indicators whenever bars or indicator config changes
  useEffect(() => {
    refreshIndicators();
  }, [refreshIndicators]);

  // Also refresh when new bar data arrives (bars set in the fetch effect)
  // We trigger by watching symbol/exchange/interval — same as the fetch effect.
  // The fetch effect sets barsRef, then on next render refreshIndicators runs.

  // --- fetch quote (LTP / change) ------------------------------------------
  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const q = await getQuotes(symbol, exchange);
        if (cancelled || !q) return;
        const ltpVal = q.ltp ?? null;
        const prevClose =
          (q as unknown as { prev_close?: number }).prev_close ??
          q.close ??
          null;
        const chg =
          ltpVal != null && prevClose != null ? ltpVal - prevClose : null;
        const chgPct =
          chg != null && prevClose ? (chg / prevClose) * 100 : null;
        if (!cancelled) {
          setLtp(ltpVal);
          setChange(chg);
          setChangePct(chgPct);
        }
      } catch {
        /* quote unavailable */
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [symbol, exchange]);

  // Live tick updates are handled by useWsBridge (Jotai atoms) — no direct
  // window event listener needed. Quote polling in the effect above keeps
  // the header LTP/change figures refreshed every symbol change.

  // --- manage horizontal lines on chart ------------------------------------
  useEffect(() => {
    const candle = candleRef.current;
    if (!candle) return;

    hlineSeriesRef.current.forEach((ref) => {
      try {
        ref._series.removePriceLine(ref._priceLine);
      } catch {
        /* already gone */
      }
    });
    hlineSeriesRef.current = [];

    hlines.forEach((price) => {
      try {
        const pl = candle.createPriceLine({
          price,
          color: "#eab308",
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: "",
        });
        hlineSeriesRef.current.push({ _priceLine: pl, _series: candle });
      } catch {
        /* ignore */
      }
    });

    return () => {
      hlineSeriesRef.current.forEach((ref) => {
        try {
          ref._series.removePriceLine(ref._priceLine);
        } catch {
          /* gone */
        }
      });
      hlineSeriesRef.current = [];
    };
  }, [hlines]);

  // --- event handlers ------------------------------------------------------
  const handleSymbolSelect = useCallback((item: SymbolSearchResult) => {
    setSymbol(item.symbol);
    setExchange(item.exchange);
    setLtp(null);
    setChange(null);
    setChangePct(null);
    setLegend(null);
    setHlines([]);
    // Clear existing indicator series so they get recreated with new data
    const chart = chartRef.current;
    if (chart) {
      const ind = indRef.current;
      const keys = Object.keys(ind) as (keyof IndicatorSeriesRefs)[];
      for (const k of keys) {
        if (ind[k]) {
          try { chart.removeSeries(ind[k]!); } catch { /* ignore */ }
          ind[k] = null;
        }
      }
    }
  }, []);

  const handleIntervalChange = useCallback((v: string) => {
    setInterval(v);
  }, []);

  const toggleDrawMode = useCallback((mode: "hline") => {
    setDrawMode((prev) => (prev === mode ? null : mode));
  }, []);

  const removeLastHline = useCallback(() => {
    setHlines((prev) => prev.slice(0, -1));
  }, []);

  const clearAllHlines = useCallback(() => {
    setHlines([]);
  }, []);

  const toggleIndicator = useCallback(
    (key: keyof IndicatorState, value: boolean) => {
      setIndicators((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  // --- derived display -----------------------------------------------------
  const isPositive = change == null ? null : change >= 0;
  const changeColor =
    change == null
      ? "text-text-secondary"
      : isPositive
        ? "text-profit"
        : "text-loss";

  const legendColor = legend
    ? legend.bull
      ? "text-profit"
      : "text-loss"
    : "text-text-primary";

  // Count active indicators for badge
  const activeIndicatorCount = [
    indicators.showEMA20,
    indicators.showEMA50,
    indicators.showBB,
    indicators.showSupertrend,
    indicators.showRSI,
    indicators.showMACD,
  ].filter(Boolean).length;

  return (
    <div className="flex flex-col h-full w-full bg-surface-base overflow-hidden">

      {/* header row */}
      <div className="flex items-center justify-between px-2 py-1 bg-surface-base border-b border-border-default shrink-0">

        {/* Left: symbol search + symbol info */}
        <div className="flex items-center gap-3 min-w-0">
          <SymbolSearch onSelect={handleSymbolSelect} />

          <div className="flex items-center gap-2 min-w-0">
            <span className="text-[12px] font-mono font-bold text-text-primary leading-none whitespace-nowrap">
              {symbol}
            </span>
            <span className="text-[10px] font-mono text-text-muted whitespace-nowrap">
              {exchange}
            </span>
            {ltp != null && (
              <span className="text-[13px] font-mono font-bold text-text-primary leading-none whitespace-nowrap">
                {formatPrice(ltp)}
              </span>
            )}
            {change != null && (
              <span
                className={`flex items-center gap-0.5 text-[11px] font-mono whitespace-nowrap ${changeColor}`}
              >
                {isPositive ? (
                  <TrendingUp size={11} />
                ) : (
                  <TrendingDown size={11} />
                )}
                {formatChange(change)} ({formatChangePct(changePct)})
              </span>
            )}
          </div>
        </div>

        {/* Right: OHLCV legend + interval pills */}
        <div className="flex items-center gap-3 shrink-0">
          {legend && (
            <div
              className={`flex items-center gap-2 text-[10px] font-mono ${legendColor}`}
            >
              <span>
                O{" "}
                <span className="text-text-primary">
                  {formatPrice(legend.open)}
                </span>
              </span>
              <span>
                H{" "}
                <span className="text-profit">
                  {formatPrice(legend.high)}
                </span>
              </span>
              <span>
                L{" "}
                <span className="text-loss">
                  {formatPrice(legend.low)}
                </span>
              </span>
              <span>
                C{" "}
                <span className="text-text-primary">
                  {formatPrice(legend.close)}
                </span>
              </span>
              {legend.volume != null && (
                <span>
                  V{" "}
                  <span className="text-text-secondary">
                    {formatVolume(legend.volume)}
                  </span>
                </span>
              )}
            </div>
          )}
          <IntervalPills
            intervals={intervals}
            active={interval}
            onSelect={handleIntervalChange}
          />
        </div>
      </div>

      {/* toolbar */}
      <div className="flex items-center gap-1 px-2 py-0.5 bg-surface-base border-b border-border-default shrink-0">

        {/* Indicators dropdown */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-[10px] gap-1 text-text-secondary hover:text-text-primary"
            >
              <BarChart2 size={11} />
              Indicators
              {activeIndicatorCount > 0 && (
                <span className="ml-0.5 bg-accent text-white rounded-full px-1 text-[9px] leading-none py-0.5">
                  {activeIndicatorCount}
                </span>
              )}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="start"
            className="w-52 bg-surface-card border-border-default text-text-primary"
          >
            <DropdownMenuLabel className="text-[10px] text-text-muted uppercase tracking-wider px-2 py-1">
              Overlays
            </DropdownMenuLabel>
            <DropdownMenuCheckboxItem
              checked={indicators.showEMA20}
              onCheckedChange={(v) => toggleIndicator("showEMA20", v)}
              className="text-[11px] gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-[#3b82f6] inline-block shrink-0" />
              EMA (20)
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showEMA50}
              onCheckedChange={(v) => toggleIndicator("showEMA50", v)}
              className="text-[11px] gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-[#f59e0b] inline-block shrink-0" />
              EMA (50)
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showBB}
              onCheckedChange={(v) => toggleIndicator("showBB", v)}
              className="text-[11px] gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-[#94a3b8] inline-block shrink-0" />
              Bollinger Bands (20, 2)
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showSupertrend}
              onCheckedChange={(v) => toggleIndicator("showSupertrend", v)}
              className="text-[11px] gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-profit inline-block shrink-0" />
              Supertrend (10, 3)
            </DropdownMenuCheckboxItem>
            <DropdownMenuSeparator className="bg-border-default" />
            <DropdownMenuLabel className="text-[10px] text-text-muted uppercase tracking-wider px-2 py-1">
              Volume
            </DropdownMenuLabel>
            <DropdownMenuCheckboxItem
              checked={indicators.showVolume}
              onCheckedChange={(v) => toggleIndicator("showVolume", v)}
              className="text-[11px] gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-[#64748b] inline-block shrink-0" />
              Volume
            </DropdownMenuCheckboxItem>
            <DropdownMenuSeparator className="bg-border-default" />
            <DropdownMenuLabel className="text-[10px] text-text-muted uppercase tracking-wider px-2 py-1">
              Oscillators
            </DropdownMenuLabel>
            <DropdownMenuCheckboxItem
              checked={indicators.showRSI}
              onCheckedChange={(v) => toggleIndicator("showRSI", v)}
              className="text-[11px] gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-[#a855f7] inline-block shrink-0" />
              RSI (14)
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showMACD}
              onCheckedChange={(v) => toggleIndicator("showMACD", v)}
              className="text-[11px] gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-[#3b82f6] inline-block shrink-0" />
              MACD (12, 26, 9)
            </DropdownMenuCheckboxItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <div className="w-px h-4 bg-border-default mx-0.5" />

        {/* Draw tools */}
        <span className="text-[9px] text-text-muted uppercase tracking-wider">
          Draw
        </span>

        <button
          onClick={() => toggleDrawMode("hline")}
          title="Horizontal line — click a price level on the chart"
          className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] transition-colors ${
            drawMode === "hline"
              ? "bg-accent text-white"
              : "text-text-secondary hover:text-text-primary hover:bg-border-default"
          }`}
        >
          <Minus size={11} />
          <span>H-Line</span>
        </button>

        {hlines.length > 0 && (
          <button
            onClick={removeLastHline}
            title="Remove last horizontal line"
            className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] text-text-secondary hover:text-loss hover:bg-border-default transition-colors"
          >
            <X size={10} />
            <span>Undo</span>
          </button>
        )}

        {hlines.length > 1 && (
          <button
            onClick={clearAllHlines}
            title="Clear all horizontal lines"
            className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] text-text-secondary hover:text-loss hover:bg-border-default transition-colors"
          >
            <X size={10} />
            <span>Clear All</span>
          </button>
        )}

        {drawMode === "hline" && (
          <span className="text-[9px] text-accent ml-1 animate-pulse">
            Click chart to place line
          </span>
        )}

        {hlines.length > 0 && (
          <span className="text-[9px] text-text-muted ml-auto">
            {hlines.length} line{hlines.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* chart area */}
      <div
        ref={containerRef}
        className="flex-1 w-full min-h-0"
        style={{ cursor: drawMode === "hline" ? "crosshair" : "default" }}
      />
    </div>
  );
}
