import { useState, useEffect, useRef, useCallback } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createSeriesMarkers,
} from "lightweight-charts";
import type {
  IChartApi,
  ISeriesApi,
  IPriceLine,
  ISeriesMarkersPluginApi,
  MouseEventParams,
  CandlestickData,
  HistogramData,
  LineData,
  Time,
  SeriesMarker,
} from "lightweight-charts";
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

// --- types -------------------------------------------------------------------

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
  showSMA: boolean;
  showWMA: boolean;
  showBB: boolean;
  showSupertrend: boolean;
  showVWAP: boolean;
  showIchimoku: boolean;
  showPivot: boolean;
  showVolume: boolean;
  showRSI: boolean;
  showMACD: boolean;
  showStoch: boolean;
  showATR: boolean;
  showADX: boolean;
  // New indicators
  showWilliamsR: boolean;
  showCCI: boolean;
  showDEMA: boolean;
  showHullMA: boolean;
  showParabolicSAR: boolean;
  showOBV: boolean;
  showKeltner: boolean;
  showVWMA: boolean;
}

interface IndicatorPeriods {
  ema1: number;
  ema2: number;
  sma: number;
  wma: number;
  bbPeriod: number;
  bbMult: number;
  stPeriod: number;
  stFactor: number;
  rsi: number;
  cci: number;
  dema: number;
  hull: number;
  wr: number;
  keltner: number;
  keltnerMult: number;
  vwma: number;
  atr: number;
  adx: number;
}

// Drawing tool types
type DrawToolType =
  | "hline"
  | "vline"
  | "trendline"
  | "ray"
  | "fib"
  | "rect"
  | "text";

interface DrawingPoint {
  time: Time;
  price: number;
}

// Each drawing is a discriminated union
interface HLineDrawing {
  kind: "hline";
  id: string;
  price: number;
}
interface VLineDrawing {
  kind: "vline";
  id: string;
  time: Time;
}
interface TrendLineDrawing {
  kind: "trendline";
  id: string;
  p1: DrawingPoint;
  p2: DrawingPoint;
}
interface RayDrawing {
  kind: "ray";
  id: string;
  p1: DrawingPoint;
  p2: DrawingPoint;
}
interface FibDrawing {
  kind: "fib";
  id: string;
  p1: DrawingPoint;
  p2: DrawingPoint;
}
interface RectDrawing {
  kind: "rect";
  id: string;
  p1: DrawingPoint;
  p2: DrawingPoint;
}
interface TextDrawing {
  kind: "text";
  id: string;
  point: DrawingPoint;
  label: string;
}

type Drawing =
  | HLineDrawing
  | VLineDrawing
  | TrendLineDrawing
  | RayDrawing
  | FibDrawing
  | RectDrawing
  | TextDrawing;

// Indicator series refs bundled together
interface IndicatorSeriesRefs {
  ema20: ISeriesApi<"Line"> | null;
  ema50: ISeriesApi<"Line"> | null;
  sma: ISeriesApi<"Line"> | null;
  wma: ISeriesApi<"Line"> | null;
  bbUpper: ISeriesApi<"Line"> | null;
  bbMiddle: ISeriesApi<"Line"> | null;
  bbLower: ISeriesApi<"Line"> | null;
  stUp: ISeriesApi<"Line"> | null;
  stDown: ISeriesApi<"Line"> | null;
  vwap: ISeriesApi<"Line"> | null;
  ichTenkan: ISeriesApi<"Line"> | null;
  ichKijun: ISeriesApi<"Line"> | null;
  ichSenkouA: ISeriesApi<"Line"> | null;
  ichSenkouB: ISeriesApi<"Line"> | null;
  ichChikou: ISeriesApi<"Line"> | null;
  rsi: ISeriesApi<"Line"> | null;
  macdLine: ISeriesApi<"Line"> | null;
  macdSignal: ISeriesApi<"Line"> | null;
  macdHist: ISeriesApi<"Histogram"> | null;
  stochK: ISeriesApi<"Line"> | null;
  stochD: ISeriesApi<"Line"> | null;
  atr: ISeriesApi<"Line"> | null;
  adx: ISeriesApi<"Line"> | null;
  adxPlus: ISeriesApi<"Line"> | null;
  adxMinus: ISeriesApi<"Line"> | null;
  // New indicators
  williamsR: ISeriesApi<"Line"> | null;
  cci: ISeriesApi<"Line"> | null;
  dema: ISeriesApi<"Line"> | null;
  hullMA: ISeriesApi<"Line"> | null;
  parSar: ISeriesApi<"Line"> | null;
  obv: ISeriesApi<"Line"> | null;
  keltnerUpper: ISeriesApi<"Line"> | null;
  keltnerMiddle: ISeriesApi<"Line"> | null;
  keltnerLower: ISeriesApi<"Line"> | null;
  vwma: ISeriesApi<"Line"> | null;
}

// Pivot price lines ref
interface PivotRefs {
  lines: IPriceLine[];
  series: ISeriesApi<"Candlestick"> | null;
}

// Drawing series refs — each drawing id maps to its series list
type DrawingSeriesMap = Map<string, ISeriesApi<"Line">[]>;

// Marker plugin ref
type MarkersPlugin = ISeriesMarkersPluginApi<Time>;

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
  showSMA: false,
  showWMA: false,
  showBB: false,
  showSupertrend: false,
  showVWAP: false,
  showIchimoku: false,
  showPivot: false,
  showVolume: true,
  showRSI: false,
  showMACD: false,
  showStoch: false,
  showATR: false,
  showADX: false,
  // New indicators
  showWilliamsR: false,
  showCCI: false,
  showDEMA: false,
  showHullMA: false,
  showParabolicSAR: false,
  showOBV: false,
  showKeltner: false,
  showVWMA: false,
};

const DEFAULT_PERIODS: IndicatorPeriods = {
  ema1: 20, ema2: 50, sma: 20, wma: 20,
  bbPeriod: 20, bbMult: 2,
  stPeriod: 10, stFactor: 3,
  rsi: 14, cci: 20, dema: 20, hull: 20, wr: 14,
  keltner: 20, keltnerMult: 2.0, vwma: 20,
  atr: 14, adx: 14,
};

const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1] as const;
const FIB_COLORS: Record<number, string> = {
  0: "#ef4444",
  0.236: "#f97316",
  0.382: "#eab308",
  0.5: "#22c55e",
  0.618: "#3b82f6",
  0.786: "#a855f7",
  1: "#ef4444",
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

function calcSMA(closes: number[], period: number): (number | null)[] {
  const result: (number | null)[] = new Array(closes.length).fill(null);
  for (let i = period - 1; i < closes.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += closes[j];
    result[i] = sum / period;
  }
  return result;
}

function calcWMA(closes: number[], period: number): (number | null)[] {
  const result: (number | null)[] = new Array(closes.length).fill(null);
  const denom = (period * (period + 1)) / 2;
  for (let i = period - 1; i < closes.length; i++) {
    let weighted = 0;
    for (let j = 0; j < period; j++) {
      weighted += closes[i - period + 1 + j] * (j + 1);
    }
    result[i] = weighted / denom;
  }
  return result;
}

function calcVWAP(bars: OhlcvBar[], times: Time[]): (number | null)[] {
  // VWAP resets daily. We group by calendar date.
  const result: (number | null)[] = new Array(bars.length).fill(null);
  let cumulativePV = 0;
  let cumulativeV = 0;
  let lastDay = "";

  for (let i = 0; i < bars.length; i++) {
    const t = times[i];
    // Extract date string from unix timestamp (seconds)
    const ts = typeof t === "number" ? t : 0;
    const d = new Date(ts * 1000);
    const day = `${d.getUTCFullYear()}-${d.getUTCMonth()}-${d.getUTCDate()}`;
    if (day !== lastDay) {
      // new day — reset
      cumulativePV = 0;
      cumulativeV = 0;
      lastDay = day;
    }
    const typicalPrice = (bars[i].high + bars[i].low + bars[i].close) / 3;
    const vol = bars[i].volume ?? 1;
    cumulativePV += typicalPrice * vol;
    cumulativeV += vol;
    result[i] = cumulativeV > 0 ? cumulativePV / cumulativeV : null;
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

interface StochResult {
  k: (number | null)[];
  d: (number | null)[];
}

function calcStochastic(
  highs: number[],
  lows: number[],
  closes: number[],
  kPeriod = 14,
  dPeriod = 3,
  smooth = 3,
): StochResult {
  const n = closes.length;
  const rawK: (number | null)[] = new Array(n).fill(null);

  for (let i = kPeriod - 1; i < n; i++) {
    const slice_h = highs.slice(i - kPeriod + 1, i + 1);
    const slice_l = lows.slice(i - kPeriod + 1, i + 1);
    const highest = Math.max(...slice_h);
    const lowest = Math.min(...slice_l);
    rawK[i] = highest !== lowest ? ((closes[i] - lowest) / (highest - lowest)) * 100 : 50;
  }

  // Smooth %K with SMA(smooth)
  const smoothK: (number | null)[] = new Array(n).fill(null);
  for (let i = kPeriod + smooth - 2; i < n; i++) {
    let sum = 0;
    let count = 0;
    for (let j = i - smooth + 1; j <= i; j++) {
      if (rawK[j] !== null) { sum += rawK[j]!; count++; }
    }
    if (count === smooth) smoothK[i] = sum / smooth;
  }

  // %D = SMA(dPeriod) of smoothed %K
  const d: (number | null)[] = new Array(n).fill(null);
  for (let i = kPeriod + smooth + dPeriod - 3; i < n; i++) {
    let sum = 0;
    let count = 0;
    for (let j = i - dPeriod + 1; j <= i; j++) {
      if (smoothK[j] !== null) { sum += smoothK[j]!; count++; }
    }
    if (count === dPeriod) d[i] = sum / dPeriod;
  }

  return { k: smoothK, d };
}

interface ATRResult {
  values: (number | null)[];
}

function calcATR(
  highs: number[],
  lows: number[],
  closes: number[],
  period = 14,
): ATRResult {
  const n = closes.length;
  const values: (number | null)[] = new Array(n).fill(null);
  if (n < period + 1) return { values };

  const tr: number[] = new Array(n).fill(0);
  tr[0] = highs[0] - lows[0];
  for (let i = 1; i < n; i++) {
    tr[i] = Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i - 1]),
      Math.abs(lows[i] - closes[i - 1]),
    );
  }

  // Seed with SMA then Wilder's smoothing
  let atr = 0;
  for (let i = 0; i < period; i++) atr += tr[i];
  atr /= period;
  values[period - 1] = atr;
  for (let i = period; i < n; i++) {
    atr = (atr * (period - 1) + tr[i]) / period;
    values[i] = atr;
  }

  return { values };
}

interface ADXResult {
  adx: (number | null)[];
  plusDI: (number | null)[];
  minusDI: (number | null)[];
}

function calcADX(
  highs: number[],
  lows: number[],
  closes: number[],
  period = 14,
): ADXResult {
  const n = closes.length;
  const adx: (number | null)[] = new Array(n).fill(null);
  const plusDI: (number | null)[] = new Array(n).fill(null);
  const minusDI: (number | null)[] = new Array(n).fill(null);

  if (n < period * 2) return { adx, plusDI, minusDI };

  const tr: number[] = new Array(n).fill(0);
  const dmPlus: number[] = new Array(n).fill(0);
  const dmMinus: number[] = new Array(n).fill(0);

  tr[0] = highs[0] - lows[0];
  for (let i = 1; i < n; i++) {
    tr[i] = Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i - 1]),
      Math.abs(lows[i] - closes[i - 1]),
    );
    const upMove = highs[i] - highs[i - 1];
    const downMove = lows[i - 1] - lows[i];
    dmPlus[i] = upMove > downMove && upMove > 0 ? upMove : 0;
    dmMinus[i] = downMove > upMove && downMove > 0 ? downMove : 0;
  }

  // Wilder's smoothing
  let smoothTR = 0;
  let smoothPlus = 0;
  let smoothMinus = 0;

  for (let i = 1; i <= period; i++) {
    smoothTR += tr[i];
    smoothPlus += dmPlus[i];
    smoothMinus += dmMinus[i];
  }

  const dx: (number | null)[] = new Array(n).fill(null);

  for (let i = period; i < n; i++) {
    if (i > period) {
      smoothTR = smoothTR - smoothTR / period + tr[i];
      smoothPlus = smoothPlus - smoothPlus / period + dmPlus[i];
      smoothMinus = smoothMinus - smoothMinus / period + dmMinus[i];
    }

    const pdi = smoothTR > 0 ? (smoothPlus / smoothTR) * 100 : 0;
    const mdi = smoothTR > 0 ? (smoothMinus / smoothTR) * 100 : 0;
    plusDI[i] = pdi;
    minusDI[i] = mdi;

    const sum = pdi + mdi;
    dx[i] = sum > 0 ? (Math.abs(pdi - mdi) / sum) * 100 : 0;
  }

  // ADX = Wilder's smooth of DX over period
  let adxVal = 0;
  let seedCount = 0;
  let seedStart = -1;
  for (let i = period; i < n; i++) {
    if (dx[i] !== null) {
      adxVal += dx[i]!;
      seedCount++;
      if (seedCount === period) {
        seedStart = i;
        adxVal /= period;
        adx[i] = adxVal;
        break;
      }
    }
  }
  if (seedStart >= 0) {
    for (let i = seedStart + 1; i < n; i++) {
      if (dx[i] !== null) {
        adxVal = (adxVal * (period - 1) + dx[i]!) / period;
        adx[i] = adxVal;
      }
    }
  }

  return { adx, plusDI, minusDI };
}

interface IchimokuResult {
  tenkan: (number | null)[];
  kijun: (number | null)[];
  senkouA: (number | null)[];
  senkouB: (number | null)[];
  chikou: (number | null)[];
}

function calcIchimoku(
  highs: number[],
  lows: number[],
  closes: number[],
  tenkanPeriod = 9,
  kijunPeriod = 26,
  senkouBPeriod = 52,
  displacement = 26,
): IchimokuResult {
  const n = closes.length;
  const tenkan: (number | null)[] = new Array(n).fill(null);
  const kijun: (number | null)[] = new Array(n).fill(null);
  const senkouA: (number | null)[] = new Array(n).fill(null);
  const senkouB: (number | null)[] = new Array(n).fill(null);
  const chikou: (number | null)[] = new Array(n).fill(null);

  function midLine(period: number, i: number): number | null {
    if (i < period - 1) return null;
    const hSlice = highs.slice(i - period + 1, i + 1);
    const lSlice = lows.slice(i - period + 1, i + 1);
    return (Math.max(...hSlice) + Math.min(...lSlice)) / 2;
  }

  for (let i = 0; i < n; i++) {
    tenkan[i] = midLine(tenkanPeriod, i);
    kijun[i] = midLine(kijunPeriod, i);
    chikou[i] = closes[i];
  }

  // Senkou A and B are displaced forward by `displacement` bars.
  // We render them at current index to show them on the right side of the chart.
  // Convention: senkouA[i] is plotted at time[i + displacement]
  // Since we can only plot at existing times, we shift the arrays.
  for (let i = 0; i < n; i++) {
    const t = tenkan[i];
    const k = kijun[i];
    if (t !== null && k !== null) {
      const target = i + displacement;
      if (target < n) {
        senkouA[target] = (t + k) / 2;
      }
    }
    const sb = midLine(senkouBPeriod, i);
    if (sb !== null) {
      const target = i + displacement;
      if (target < n) {
        senkouB[target] = sb;
      }
    }
  }

  return { tenkan, kijun, senkouA, senkouB, chikou };
}

interface PivotResult {
  pp: number;
  r1: number;
  r2: number;
  r3: number;
  s1: number;
  s2: number;
  s3: number;
}

function calcPivotPoints(bars: OhlcvBar[]): PivotResult | null {
  if (bars.length < 2) return null;
  // Use previous session (last completed day if on intraday, else previous bar)
  // Simple approach: use the second-to-last bar's H/L/C
  const prev = bars[bars.length - 2];
  const pp = (prev.high + prev.low + prev.close) / 3;
  const r1 = 2 * pp - prev.low;
  const s1 = 2 * pp - prev.high;
  const r2 = pp + (prev.high - prev.low);
  const s2 = pp - (prev.high - prev.low);
  const r3 = prev.high + 2 * (pp - prev.low);
  const s3 = prev.low - 2 * (prev.high - pp);
  return { pp, r1, r2, r3, s1, s2, s3 };
}

// --- new indicator calculation functions ------------------------------------

function calcWilliamsR(
  highs: number[],
  lows: number[],
  closes: number[],
  period = 14,
): (number | null)[] {
  const n = closes.length;
  const result: (number | null)[] = new Array(n).fill(null);
  for (let i = period - 1; i < n; i++) {
    const sliceH = highs.slice(i - period + 1, i + 1);
    const sliceL = lows.slice(i - period + 1, i + 1);
    const hh = Math.max(...sliceH);
    const ll = Math.min(...sliceL);
    const range = hh - ll;
    result[i] = range === 0 ? 0 : ((hh - closes[i]) / range) * -100;
  }
  return result;
}

function calcCCI(
  highs: number[],
  lows: number[],
  closes: number[],
  period = 20,
): (number | null)[] {
  const n = closes.length;
  const result: (number | null)[] = new Array(n).fill(null);
  for (let i = period - 1; i < n; i++) {
    let sumTP = 0;
    for (let j = i - period + 1; j <= i; j++) {
      sumTP += (highs[j] + lows[j] + closes[j]) / 3;
    }
    const meanTP = sumTP / period;
    let meanDev = 0;
    for (let j = i - period + 1; j <= i; j++) {
      meanDev += Math.abs((highs[j] + lows[j] + closes[j]) / 3 - meanTP);
    }
    meanDev /= period;
    const tp = (highs[i] + lows[i] + closes[i]) / 3;
    result[i] = meanDev === 0 ? 0 : (tp - meanTP) / (0.015 * meanDev);
  }
  return result;
}

function calcDEMA(closes: number[], period = 20): (number | null)[] {
  const ema1 = calcEMA(closes, period);
  // EMA of EMA — only over the non-null portion
  const ema1Vals: number[] = [];
  const ema1Idx: number[] = [];
  for (let i = 0; i < ema1.length; i++) {
    if (ema1[i] !== null) { ema1Vals.push(ema1[i]!); ema1Idx.push(i); }
  }
  const ema2Inner = calcEMA(ema1Vals, period);
  const n = closes.length;
  const ema2: (number | null)[] = new Array(n).fill(null);
  for (let j = 0; j < ema1Idx.length; j++) {
    ema2[ema1Idx[j]] = ema2Inner[j];
  }
  const result: (number | null)[] = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    if (ema1[i] !== null && ema2[i] !== null) {
      result[i] = 2 * ema1[i]! - ema2[i]!;
    }
  }
  return result;
}

function calcHullMA(closes: number[], period = 20): (number | null)[] {
  const half = Math.floor(period / 2);
  const sqrtP = Math.round(Math.sqrt(period));
  const wmaFull = calcWMA(closes, period);
  const wmaHalf = calcWMA(closes, half);
  // 2 * WMA(n/2) - WMA(n)
  const n = closes.length;
  const diff: (number | null)[] = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    if (wmaHalf[i] !== null && wmaFull[i] !== null) {
      diff[i] = 2 * wmaHalf[i]! - wmaFull[i]!;
    }
  }
  // WMA of diff with sqrt(n) period — only over non-null diff values
  const diffVals: number[] = [];
  const diffIdx: number[] = [];
  for (let i = 0; i < n; i++) {
    if (diff[i] !== null) { diffVals.push(diff[i]!); diffIdx.push(i); }
  }
  const hmaInner = calcWMA(diffVals, sqrtP);
  const result: (number | null)[] = new Array(n).fill(null);
  for (let j = 0; j < diffIdx.length; j++) {
    result[diffIdx[j]] = hmaInner[j];
  }
  return result;
}

function calcParabolicSAR(
  highs: number[],
  lows: number[],
  af = 0.02,
  maxAf = 0.2,
): (number | null)[] {
  const n = highs.length;
  const result: (number | null)[] = new Array(n).fill(null);
  if (n < 2) return result;

  let isRising = true;
  let sar = lows[0];
  let ep = highs[0];
  let currentAf = af;

  for (let i = 1; i < n; i++) {
    const prevSar = sar;
    sar = prevSar + currentAf * (ep - prevSar);

    if (isRising) {
      sar = Math.min(sar, lows[i - 1]);
      if (i >= 2) sar = Math.min(sar, lows[i - 2]);
      if (highs[i] > ep) {
        ep = highs[i];
        currentAf = Math.min(currentAf + af, maxAf);
      }
      if (lows[i] < sar) {
        isRising = false;
        sar = ep;
        ep = lows[i];
        currentAf = af;
      }
    } else {
      sar = Math.max(sar, highs[i - 1]);
      if (i >= 2) sar = Math.max(sar, highs[i - 2]);
      if (lows[i] < ep) {
        ep = lows[i];
        currentAf = Math.min(currentAf + af, maxAf);
      }
      if (highs[i] > sar) {
        isRising = true;
        sar = ep;
        ep = highs[i];
        currentAf = af;
      }
    }
    result[i] = sar;
  }
  return result;
}

function calcOBV(closes: number[], volumes: number[]): (number | null)[] {
  const n = closes.length;
  const result: (number | null)[] = new Array(n).fill(null);
  if (n === 0) return result;
  result[0] = 0;
  for (let i = 1; i < n; i++) {
    const prev = result[i - 1]!;
    if (closes[i] > closes[i - 1]) result[i] = prev + volumes[i];
    else if (closes[i] < closes[i - 1]) result[i] = prev - volumes[i];
    else result[i] = prev;
  }
  return result;
}

interface KeltnerResult {
  upper: (number | null)[];
  middle: (number | null)[];
  lower: (number | null)[];
}

function calcKeltnerChannels(
  bars: OhlcvBar[],
  period = 20,
  mult = 2.0,
): KeltnerResult {
  const n = bars.length;
  const highs = bars.map((b) => b.high);
  const lows = bars.map((b) => b.low);
  const closes = bars.map((b) => b.close);
  const middle = calcEMA(closes, period);
  const atrVals = calcATR(highs, lows, closes).values;
  const upper: (number | null)[] = new Array(n).fill(null);
  const lower: (number | null)[] = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    if (middle[i] !== null && atrVals[i] !== null) {
      upper[i] = middle[i]! + mult * atrVals[i]!;
      lower[i] = middle[i]! - mult * atrVals[i]!;
    }
  }
  return { upper, middle, lower };
}

function calcVWMA(bars: OhlcvBar[], period = 20): (number | null)[] {
  const n = bars.length;
  const result: (number | null)[] = new Array(n).fill(null);
  for (let i = period - 1; i < n; i++) {
    let sumCV = 0;
    let sumV = 0;
    for (let j = i - period + 1; j <= i; j++) {
      const vol = bars[j].volume ?? 1;
      sumCV += bars[j].close * vol;
      sumV += vol;
    }
    result[i] = sumV > 0 ? sumCV / sumV : null;
  }
  return result;
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
): { time: Time; value: number; color: string }[] {
  const out: { time: Time; value: number; color: string }[] = [];
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

function uid(): string {
  return Math.random().toString(36).slice(2, 10);
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
        {loading && (
          <span className="text-text-muted text-xs shrink-0 animate-pulse">
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
                  : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
              }`}
            >
              <span className="flex flex-col gap-0.5">
                <span className="text-xs font-mono font-semibold text-text-primary">
                  {item.symbol}
                </span>
                {item.name && (
                  <span className="text-xs text-text-muted truncate max-w-40">
                    {item.name}
                  </span>
                )}
              </span>
              <span className="flex flex-col items-end gap-0.5">
                <span className="text-xs font-mono text-accent">
                  {item.exchange}
                </span>
                {item.instrument_type && (
                  <span className="text-xxs text-text-muted uppercase">
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
          className={`px-2 py-1 text-xs font-mono rounded transition-colors ${
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

// Drawing tool button component
interface DrawToolBtnProps {
  toolId: DrawToolType;
  active: DrawToolType | null;
  onClick: (t: DrawToolType) => void;
  title: string;
  children: React.ReactNode;
}

function DrawToolBtn({ toolId, active, onClick, title, children }: DrawToolBtnProps) {
  return (
    <button
      onClick={() => onClick(toolId)}
      title={title}
      className={`flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors ${
        active === toolId
          ? "bg-accent/15 text-accent"
          : "text-text-secondary hover:text-text-primary hover:bg-surface-hover"
      }`}
    >
      {children}
    </button>
  );
}

// Text annotation dialog
interface TextInputOverlayProps {
  onConfirm: (text: string) => void;
  onCancel: () => void;
}

function TextInputOverlay({ onConfirm, onCancel }: TextInputOverlayProps) {
  const [val, setVal] = useState("");
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    ref.current?.focus();
  }, []);

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
      <button
        onClick={() => val.trim() && onConfirm(val.trim())}
        className="text-xs bg-accent text-white px-2 py-0.5 rounded"
      >
        Place
      </button>
      <button
        onClick={onCancel}
        className="text-xs text-text-muted hover:text-loss px-1"
      >
        <X size={11} />
      </button>
    </div>
  );
}

// --- period input helper -----------------------------------------------------

function PeriodInput({
  value,
  onChange,
}: {
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <Input
      type="number"
      min={2}
      max={500}
      value={value}
      className="w-11 h-6 text-xs font-mono text-center px-1 py-0 ml-auto bg-surface-card border-border-default rounded"
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
      onChange={(e) => {
        const v = parseInt(e.target.value, 10);
        if (!isNaN(v) && v >= 2 && v <= 500) onChange(v);
      }}
    />
  );
}

// --- main component ----------------------------------------------------------

export default function ChartWidget() {
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
  const [drawMode, setDrawMode] = useState<DrawToolType | null>(null);
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  // pending first-point click for two-click tools
  const [pendingPoint, setPendingPoint] = useState<DrawingPoint | null>(null);
  // pending text placement
  const [awaitingText, setAwaitingText] = useState<DrawingPoint | null>(null);

  // indicator toggles
  const [indicators, setIndicators] = useState<IndicatorState>(DEFAULT_INDICATORS);
  const [periods, setPeriods] = useState<IndicatorPeriods>(DEFAULT_PERIODS);

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
    sma: null,
    wma: null,
    bbUpper: null,
    bbMiddle: null,
    bbLower: null,
    stUp: null,
    stDown: null,
    vwap: null,
    ichTenkan: null,
    ichKijun: null,
    ichSenkouA: null,
    ichSenkouB: null,
    ichChikou: null,
    rsi: null,
    macdLine: null,
    macdSignal: null,
    macdHist: null,
    stochK: null,
    stochD: null,
    atr: null,
    adx: null,
    adxPlus: null,
    adxMinus: null,
    williamsR: null,
    cci: null,
    dema: null,
    hullMA: null,
    parSar: null,
    obv: null,
    keltnerUpper: null,
    keltnerMiddle: null,
    keltnerLower: null,
    vwma: null,
  });

  // pivot price lines
  const pivotRef = useRef<PivotRefs>({ lines: [], series: null });

  // drawing series map: drawingId -> list of LineSeries used
  const drawingSeriesRef = useRef<DrawingSeriesMap>(new Map());

  // hline drawing ref (legacy compat with new unified drawings array)
  const hlineSeriesRef = useRef<HlineRef[]>([]);

  // markers plugin for text annotations
  const markersPluginRef = useRef<MarkersPlugin | null>(null);
  const textMarkersRef = useRef<SeriesMarker<Time>[]>([]);

  // drawMode ref for click handler closure
  const drawModeRef = useRef<DrawToolType | null>(drawMode);
  useEffect(() => {
    drawModeRef.current = drawMode;
  }, [drawMode]);

  // pendingPoint ref for click handler closure
  const pendingPointRef = useRef<DrawingPoint | null>(pendingPoint);
  useEffect(() => {
    pendingPointRef.current = pendingPoint;
  }, [pendingPoint]);

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

    // Attach markers plugin to candle series for text annotations
    markersPluginRef.current = createSeriesMarkers(candleSeries, []);

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
      markersPluginRef.current = null;
      hlineSeriesRef.current = [];
      drawingSeriesRef.current.clear();
      indRef.current = {
        ema20: null, ema50: null, sma: null, wma: null,
        bbUpper: null, bbMiddle: null, bbLower: null,
        stUp: null, stDown: null,
        vwap: null,
        ichTenkan: null, ichKijun: null, ichSenkouA: null, ichSenkouB: null, ichChikou: null,
        rsi: null,
        macdLine: null, macdSignal: null, macdHist: null,
        stochK: null, stochD: null,
        atr: null,
        adx: null, adxPlus: null, adxMinus: null,
        williamsR: null, cci: null, dema: null, hullMA: null,
        parSar: null, obv: null,
        keltnerUpper: null, keltnerMiddle: null, keltnerLower: null,
        vwma: null,
      };
      pivotRef.current = { lines: [], series: null };
    };
  }, []); // chart created once

  // Re-subscribe chart click handler whenever drawMode changes
  useEffect(() => {
    const chart = chartRef.current;
    const candle = candleRef.current;
    if (!chart || !candle) return;

    if (clickHandlerRef.current) {
      chart.unsubscribeClick(clickHandlerRef.current);
    }

    const handler = (param: MouseEventParams) => {
      const mode = drawModeRef.current;
      if (!param || !param.point || !mode) return;
      const price = candle.coordinateToPrice(param.point.y);
      if (price == null) return;
      const time = param.time as Time | undefined;
      if (!time) return;

      const point: DrawingPoint = { time, price };

      if (mode === "hline") {
        setDrawings((prev) => [...prev, { kind: "hline", id: uid(), price }]);
        return;
      }

      if (mode === "vline") {
        setDrawings((prev) => [...prev, { kind: "vline", id: uid(), time }]);
        return;
      }

      if (mode === "text") {
        // Show text input dialog
        setAwaitingText(point);
        return;
      }

      // Two-click tools: trendline, ray, fib, rect
      const pending = pendingPointRef.current;
      if (!pending) {
        setPendingPoint(point);
        return;
      }

      // Second click — commit the drawing
      const id = uid();
      if (mode === "trendline") {
        setDrawings((prev) => [
          ...prev,
          { kind: "trendline", id, p1: pending, p2: point },
        ]);
      } else if (mode === "ray") {
        setDrawings((prev) => [
          ...prev,
          { kind: "ray", id, p1: pending, p2: point },
        ]);
      } else if (mode === "fib") {
        setDrawings((prev) => [
          ...prev,
          { kind: "fib", id, p1: pending, p2: point },
        ]);
      } else if (mode === "rect") {
        setDrawings((prev) => [
          ...prev,
          { kind: "rect", id, p1: pending, p2: point },
        ]);
      }
      setPendingPoint(null);
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

    // Helper to remove a series safely (chart is non-null here — guarded above)
    const safeChart = chart;
    function removeSeries(s: ISeriesApi<"Line"> | ISeriesApi<"Histogram"> | null) {
      if (!s) return;
      try { safeChart.removeSeries(s); } catch { /* ignore */ }
    }

    // --- EMA 20 ---
    if (indicators.showEMA20) {
      if (!ind.ema20) {
        ind.ema20 = chart.addSeries(LineSeries, {
          color: "#3b82f6", lineWidth: 1, priceScaleId: "right",
          title: `EMA${periods.ema1}`, lastValueVisible: false, priceLineVisible: false,
        });
      }
      ind.ema20.applyOptions({ title: `EMA${periods.ema1}` });
      ind.ema20.setData(buildLineData(times, calcEMA(closes, periods.ema1)));
    } else if (ind.ema20) {
      removeSeries(ind.ema20); ind.ema20 = null;
    }

    // --- EMA 50 ---
    if (indicators.showEMA50) {
      if (!ind.ema50) {
        ind.ema50 = chart.addSeries(LineSeries, {
          color: "#f59e0b", lineWidth: 1, priceScaleId: "right",
          title: `EMA${periods.ema2}`, lastValueVisible: false, priceLineVisible: false,
        });
      }
      ind.ema50.applyOptions({ title: `EMA${periods.ema2}` });
      ind.ema50.setData(buildLineData(times, calcEMA(closes, periods.ema2)));
    } else if (ind.ema50) {
      removeSeries(ind.ema50); ind.ema50 = null;
    }

    // --- SMA ---
    if (indicators.showSMA) {
      if (!ind.sma) {
        ind.sma = chart.addSeries(LineSeries, {
          color: "#06b6d4", lineWidth: 1, priceScaleId: "right",
          title: `SMA${periods.sma}`, lastValueVisible: false, priceLineVisible: false,
        });
      }
      ind.sma.applyOptions({ title: `SMA${periods.sma}` });
      ind.sma.setData(buildLineData(times, calcSMA(closes, periods.sma)));
    } else if (ind.sma) {
      removeSeries(ind.sma); ind.sma = null;
    }

    // --- WMA ---
    if (indicators.showWMA) {
      if (!ind.wma) {
        ind.wma = chart.addSeries(LineSeries, {
          color: "#84cc16", lineWidth: 1, priceScaleId: "right",
          title: `WMA${periods.wma}`, lastValueVisible: false, priceLineVisible: false,
        });
      }
      ind.wma.applyOptions({ title: `WMA${periods.wma}` });
      ind.wma.setData(buildLineData(times, calcWMA(closes, periods.wma)));
    } else if (ind.wma) {
      removeSeries(ind.wma); ind.wma = null;
    }

    // --- Bollinger Bands ---
    if (indicators.showBB) {
      const bb = calcBollingerBands(closes, periods.bbPeriod, periods.bbMult);
      if (!ind.bbUpper) {
        ind.bbUpper = chart.addSeries(LineSeries, {
          color: "#ef4444", lineWidth: 1, lineStyle: 2, priceScaleId: "right",
          title: "BB Upper", lastValueVisible: false, priceLineVisible: false,
        });
      }
      if (!ind.bbMiddle) {
        ind.bbMiddle = chart.addSeries(LineSeries, {
          color: "#94a3b8", lineWidth: 1, lineStyle: 1, priceScaleId: "right",
          title: "BB Mid", lastValueVisible: false, priceLineVisible: false,
        });
      }
      if (!ind.bbLower) {
        ind.bbLower = chart.addSeries(LineSeries, {
          color: "#22c55e", lineWidth: 1, lineStyle: 2, priceScaleId: "right",
          title: "BB Lower", lastValueVisible: false, priceLineVisible: false,
        });
      }
      ind.bbUpper.setData(buildLineData(times, bb.upper));
      ind.bbMiddle.setData(buildLineData(times, bb.middle));
      ind.bbLower.setData(buildLineData(times, bb.lower));
    } else {
      for (const key of ["bbUpper", "bbMiddle", "bbLower"] as const) {
        if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; }
      }
    }

    // --- Supertrend ---
    if (indicators.showSupertrend) {
      const st = calcSupertrend(highs, lows, closes, periods.stPeriod, periods.stFactor);
      if (!ind.stUp) {
        ind.stUp = chart.addSeries(LineSeries, {
          color: "#22c55e", lineWidth: 2, priceScaleId: "right",
          title: "ST Up", lastValueVisible: false, priceLineVisible: false,
        });
      }
      if (!ind.stDown) {
        ind.stDown = chart.addSeries(LineSeries, {
          color: "#ef4444", lineWidth: 2, priceScaleId: "right",
          title: "ST Down", lastValueVisible: false, priceLineVisible: false,
        });
      }
      ind.stUp.setData(buildLineData(times, st.up));
      ind.stDown.setData(buildLineData(times, st.down));
    } else {
      for (const key of ["stUp", "stDown"] as const) {
        if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; }
      }
    }

    // --- VWAP ---
    if (indicators.showVWAP) {
      if (!ind.vwap) {
        ind.vwap = chart.addSeries(LineSeries, {
          color: "#e879f9", lineWidth: 1, lineStyle: 0, priceScaleId: "right",
          title: "VWAP", lastValueVisible: true, priceLineVisible: false,
        });
      }
      ind.vwap.setData(buildLineData(times, calcVWAP(bars, times)));
    } else if (ind.vwap) {
      removeSeries(ind.vwap); ind.vwap = null;
    }

    // --- Ichimoku Cloud ---
    if (indicators.showIchimoku) {
      const ichi = calcIchimoku(highs, lows, closes);
      if (!ind.ichTenkan) {
        ind.ichTenkan = chart.addSeries(LineSeries, {
          color: "#ef4444", lineWidth: 1, priceScaleId: "right",
          title: "Tenkan", lastValueVisible: false, priceLineVisible: false,
        });
      }
      if (!ind.ichKijun) {
        ind.ichKijun = chart.addSeries(LineSeries, {
          color: "#3b82f6", lineWidth: 1, priceScaleId: "right",
          title: "Kijun", lastValueVisible: false, priceLineVisible: false,
        });
      }
      if (!ind.ichSenkouA) {
        ind.ichSenkouA = chart.addSeries(LineSeries, {
          color: "rgba(34,197,94,0.5)", lineWidth: 1, priceScaleId: "right",
          title: "Senkou A", lastValueVisible: false, priceLineVisible: false,
        });
      }
      if (!ind.ichSenkouB) {
        ind.ichSenkouB = chart.addSeries(LineSeries, {
          color: "rgba(239,68,68,0.5)", lineWidth: 1, priceScaleId: "right",
          title: "Senkou B", lastValueVisible: false, priceLineVisible: false,
        });
      }
      if (!ind.ichChikou) {
        ind.ichChikou = chart.addSeries(LineSeries, {
          color: "#a855f7", lineWidth: 1, lineStyle: 2, priceScaleId: "right",
          title: "Chikou", lastValueVisible: false, priceLineVisible: false,
        });
      }
      ind.ichTenkan.setData(buildLineData(times, ichi.tenkan));
      ind.ichKijun.setData(buildLineData(times, ichi.kijun));
      ind.ichSenkouA.setData(buildLineData(times, ichi.senkouA));
      ind.ichSenkouB.setData(buildLineData(times, ichi.senkouB));
      // Chikou is plotted 26 bars back — shift the close array
      const chikouValues: (number | null)[] = new Array(closes.length).fill(null);
      const displacement = 26;
      for (let i = displacement; i < closes.length; i++) {
        chikouValues[i - displacement] = closes[i];
      }
      ind.ichChikou.setData(buildLineData(times, chikouValues));
    } else {
      for (const key of ["ichTenkan", "ichKijun", "ichSenkouA", "ichSenkouB", "ichChikou"] as const) {
        if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; }
      }
    }

    // --- Pivot Points ---
    if (indicators.showPivot) {
      const pivots = calcPivotPoints(bars);
      // Clear old pivot price lines
      if (pivotRef.current.series && pivotRef.current.lines.length > 0) {
        for (const pl of pivotRef.current.lines) {
          try { pivotRef.current.series.removePriceLine(pl); } catch { /* ignore */ }
        }
        pivotRef.current.lines = [];
      }
      const candle = candleRef.current;
      if (pivots && candle) {
        pivotRef.current.series = candle;
        const pivotLevels: [number, string, string][] = [
          [pivots.pp,  "#94a3b8", "PP"],
          [pivots.r1,  "#ef4444", "R1"],
          [pivots.r2,  "#f97316", "R2"],
          [pivots.r3,  "#dc2626", "R3"],
          [pivots.s1,  "#22c55e", "S1"],
          [pivots.s2,  "#16a34a", "S2"],
          [pivots.s3,  "#15803d", "S3"],
        ];
        for (const [price, color, title] of pivotLevels) {
          try {
            const pl = candle.createPriceLine({
              price, color, lineWidth: 1, lineStyle: 2,
              axisLabelVisible: true, title,
            });
            pivotRef.current.lines.push(pl);
          } catch { /* ignore */ }
        }
      }
    } else {
      if (pivotRef.current.series && pivotRef.current.lines.length > 0) {
        for (const pl of pivotRef.current.lines) {
          try { pivotRef.current.series.removePriceLine(pl); } catch { /* ignore */ }
        }
        pivotRef.current.lines = [];
        pivotRef.current.series = null;
      }
    }

    // --- Volume ---
    if (volumeRef.current) {
      volumeRef.current.applyOptions({ visible: indicators.showVolume });
    }

    // --- RSI ---
    if (indicators.showRSI) {
      if (!ind.rsi) {
        ind.rsi = chart.addSeries(LineSeries, {
          color: "#a855f7", lineWidth: 1, priceScaleId: "rsi",
          title: `RSI(${periods.rsi})`, lastValueVisible: true, priceLineVisible: false,
        });
        chart.priceScale("rsi").applyOptions({ scaleMargins: { top: 0.75, bottom: 0.05 } });
      }
      ind.rsi.applyOptions({ title: `RSI(${periods.rsi})` });
      ind.rsi.setData(buildLineData(times, calcRSI(closes, periods.rsi).values));
    } else if (ind.rsi) {
      removeSeries(ind.rsi); ind.rsi = null;
    }

    // --- MACD ---
    if (indicators.showMACD) {
      const macdData = calcMACD(closes);
      if (!ind.macdHist) {
        ind.macdHist = chart.addSeries(HistogramSeries, {
          priceScaleId: "macd", title: "MACD Hist",
          lastValueVisible: false, priceLineVisible: false,
        });
        chart.priceScale("macd").applyOptions({ scaleMargins: { top: 0.6, bottom: 0.05 } });
      }
      if (!ind.macdLine) {
        ind.macdLine = chart.addSeries(LineSeries, {
          color: "#3b82f6", lineWidth: 1, priceScaleId: "macd",
          title: "MACD", lastValueVisible: false, priceLineVisible: false,
        });
      }
      if (!ind.macdSignal) {
        ind.macdSignal = chart.addSeries(LineSeries, {
          color: "#f97316", lineWidth: 1, priceScaleId: "macd",
          title: "Signal", lastValueVisible: false, priceLineVisible: false,
        });
      }
      ind.macdHist.setData(buildHistData(times, macdData.hist));
      ind.macdLine.setData(buildLineData(times, macdData.macd));
      ind.macdSignal.setData(buildLineData(times, macdData.signal));
    } else {
      for (const key of ["macdHist", "macdLine", "macdSignal"] as const) {
        if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; }
      }
    }

    // --- Stochastic ---
    if (indicators.showStoch) {
      const stoch = calcStochastic(highs, lows, closes);
      if (!ind.stochK) {
        ind.stochK = chart.addSeries(LineSeries, {
          color: "#3b82f6", lineWidth: 1, priceScaleId: "stoch",
          title: "%K", lastValueVisible: false, priceLineVisible: false,
        });
        chart.priceScale("stoch").applyOptions({ scaleMargins: { top: 0.65, bottom: 0.05 } });
      }
      if (!ind.stochD) {
        ind.stochD = chart.addSeries(LineSeries, {
          color: "#f97316", lineWidth: 1, priceScaleId: "stoch",
          title: "%D", lastValueVisible: false, priceLineVisible: false,
        });
      }
      ind.stochK.setData(buildLineData(times, stoch.k));
      ind.stochD.setData(buildLineData(times, stoch.d));
    } else {
      for (const key of ["stochK", "stochD"] as const) {
        if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; }
      }
    }

    // --- ATR ---
    if (indicators.showATR) {
      if (!ind.atr) {
        ind.atr = chart.addSeries(LineSeries, {
          color: "#fb923c", lineWidth: 1, priceScaleId: "atr",
          title: `ATR(${periods.atr})`, lastValueVisible: true, priceLineVisible: false,
        });
        chart.priceScale("atr").applyOptions({ scaleMargins: { top: 0.7, bottom: 0.05 } });
      }
      ind.atr.applyOptions({ title: `ATR(${periods.atr})` });
      ind.atr.setData(buildLineData(times, calcATR(highs, lows, closes, periods.atr).values));
    } else if (ind.atr) {
      removeSeries(ind.atr); ind.atr = null;
    }

    // --- ADX ---
    if (indicators.showADX) {
      const adxData = calcADX(highs, lows, closes, periods.adx);
      if (!ind.adx) {
        ind.adx = chart.addSeries(LineSeries, {
          color: "#fbbf24", lineWidth: 1, priceScaleId: "adx",
          title: "ADX", lastValueVisible: true, priceLineVisible: false,
        });
        chart.priceScale("adx").applyOptions({ scaleMargins: { top: 0.65, bottom: 0.05 } });
      }
      if (!ind.adxPlus) {
        ind.adxPlus = chart.addSeries(LineSeries, {
          color: "#22c55e", lineWidth: 1, priceScaleId: "adx",
          title: "+DI", lastValueVisible: false, priceLineVisible: false,
        });
      }
      if (!ind.adxMinus) {
        ind.adxMinus = chart.addSeries(LineSeries, {
          color: "#ef4444", lineWidth: 1, priceScaleId: "adx",
          title: "-DI", lastValueVisible: false, priceLineVisible: false,
        });
      }
      ind.adx.setData(buildLineData(times, adxData.adx));
      ind.adxPlus.setData(buildLineData(times, adxData.plusDI));
      ind.adxMinus.setData(buildLineData(times, adxData.minusDI));
    } else {
      for (const key of ["adx", "adxPlus", "adxMinus"] as const) {
        if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; }
      }
    }

    // --- Williams %R ---
    if (indicators.showWilliamsR) {
      if (!ind.williamsR) {
        ind.williamsR = chart.addSeries(LineSeries, {
          color: "#f472b6", lineWidth: 1, priceScaleId: "wr",
          title: `W%R(${periods.wr})`, lastValueVisible: true, priceLineVisible: false,
        });
        chart.priceScale("wr").applyOptions({ scaleMargins: { top: 0.7, bottom: 0.05 } });
      }
      ind.williamsR.applyOptions({ title: `W%R(${periods.wr})` });
      ind.williamsR.setData(buildLineData(times, calcWilliamsR(highs, lows, closes, periods.wr)));
    } else if (ind.williamsR) {
      removeSeries(ind.williamsR); ind.williamsR = null;
    }

    // --- CCI ---
    if (indicators.showCCI) {
      if (!ind.cci) {
        ind.cci = chart.addSeries(LineSeries, {
          color: "#38bdf8", lineWidth: 1, priceScaleId: "cci",
          title: `CCI(${periods.cci})`, lastValueVisible: true, priceLineVisible: false,
        });
        chart.priceScale("cci").applyOptions({ scaleMargins: { top: 0.7, bottom: 0.05 } });
      }
      ind.cci.applyOptions({ title: `CCI(${periods.cci})` });
      ind.cci.setData(buildLineData(times, calcCCI(highs, lows, closes, periods.cci)));
    } else if (ind.cci) {
      removeSeries(ind.cci); ind.cci = null;
    }

    // --- DEMA ---
    if (indicators.showDEMA) {
      if (!ind.dema) {
        ind.dema = chart.addSeries(LineSeries, {
          color: "#f97316", lineWidth: 1, priceScaleId: "right",
          title: `DEMA${periods.dema}`, lastValueVisible: false, priceLineVisible: false,
        });
      }
      ind.dema.applyOptions({ title: `DEMA${periods.dema}` });
      ind.dema.setData(buildLineData(times, calcDEMA(closes, periods.dema)));
    } else if (ind.dema) {
      removeSeries(ind.dema); ind.dema = null;
    }

    // --- Hull MA ---
    if (indicators.showHullMA) {
      if (!ind.hullMA) {
        ind.hullMA = chart.addSeries(LineSeries, {
          color: "#a855f7", lineWidth: 1, priceScaleId: "right",
          title: `HMA${periods.hull}`, lastValueVisible: false, priceLineVisible: false,
        });
      }
      ind.hullMA.applyOptions({ title: `HMA${periods.hull}` });
      ind.hullMA.setData(buildLineData(times, calcHullMA(closes, periods.hull)));
    } else if (ind.hullMA) {
      removeSeries(ind.hullMA); ind.hullMA = null;
    }

    // --- Parabolic SAR ---
    if (indicators.showParabolicSAR) {
      if (!ind.parSar) {
        ind.parSar = chart.addSeries(LineSeries, {
          color: "#facc15", lineWidth: 1, priceScaleId: "right",
          title: "SAR", lastValueVisible: false, priceLineVisible: false,
          pointMarkersVisible: true,
        });
      }
      ind.parSar.setData(buildLineData(times, calcParabolicSAR(highs, lows)));
    } else if (ind.parSar) {
      removeSeries(ind.parSar); ind.parSar = null;
    }

    // --- OBV ---
    if (indicators.showOBV) {
      const volumes = bars.map((b) => b.volume ?? 0);
      if (!ind.obv) {
        ind.obv = chart.addSeries(LineSeries, {
          color: "#94a3b8", lineWidth: 1, priceScaleId: "obv",
          title: "OBV", lastValueVisible: true, priceLineVisible: false,
        });
        chart.priceScale("obv").applyOptions({ scaleMargins: { top: 0.7, bottom: 0.05 } });
      }
      ind.obv.setData(buildLineData(times, calcOBV(closes, volumes)));
    } else if (ind.obv) {
      removeSeries(ind.obv); ind.obv = null;
    }

    // --- Keltner Channels ---
    if (indicators.showKeltner) {
      const kc = calcKeltnerChannels(bars, periods.keltner, periods.keltnerMult);
      if (!ind.keltnerUpper) {
        ind.keltnerUpper = chart.addSeries(LineSeries, {
          color: "rgba(249,115,22,0.4)", lineWidth: 1, lineStyle: 2, priceScaleId: "right",
          title: "KC Upper", lastValueVisible: false, priceLineVisible: false,
        });
      }
      if (!ind.keltnerMiddle) {
        ind.keltnerMiddle = chart.addSeries(LineSeries, {
          color: "#f97316", lineWidth: 1, priceScaleId: "right",
          title: "KC Mid", lastValueVisible: false, priceLineVisible: false,
        });
      }
      if (!ind.keltnerLower) {
        ind.keltnerLower = chart.addSeries(LineSeries, {
          color: "rgba(249,115,22,0.4)", lineWidth: 1, lineStyle: 2, priceScaleId: "right",
          title: "KC Lower", lastValueVisible: false, priceLineVisible: false,
        });
      }
      ind.keltnerUpper.setData(buildLineData(times, kc.upper));
      ind.keltnerMiddle.setData(buildLineData(times, kc.middle));
      ind.keltnerLower.setData(buildLineData(times, kc.lower));
    } else {
      for (const key of ["keltnerUpper", "keltnerMiddle", "keltnerLower"] as const) {
        if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; }
      }
    }

    // --- VWMA ---
    if (indicators.showVWMA) {
      if (!ind.vwma) {
        ind.vwma = chart.addSeries(LineSeries, {
          color: "#2dd4bf", lineWidth: 1, priceScaleId: "right",
          title: `VWMA${periods.vwma}`, lastValueVisible: false, priceLineVisible: false,
        });
      }
      ind.vwma.applyOptions({ title: `VWMA${periods.vwma}` });
      ind.vwma.setData(buildLineData(times, calcVWMA(bars, periods.vwma)));
    } else if (ind.vwma) {
      removeSeries(ind.vwma); ind.vwma = null;
    }
  }, [indicators, periods]);

  // Refresh indicators whenever bars or indicator config changes
  useEffect(() => {
    refreshIndicators();
  }, [refreshIndicators]);

  // --- manage drawings on the chart ----------------------------------------
  // We re-render all drawings whenever the `drawings` array changes.
  // Strategy per drawing kind:
  //   hline  → createPriceLine on candleSeries
  //   vline  → LineSeries with single-time data at that bar, priceScaleId "right", value = 0
  //            (not a true vertical, but renders as a price marker; see note below)
  //   trendline → LineSeries with 2 points
  //   ray    → LineSeries with 2 points; second point time extended far right
  //   fib    → multiple createPriceLine per level
  //   rect   → 2 createPriceLine (top + bottom) for horizontal bounds
  //   text   → createSeriesMarkers
  //
  // Note on vline: lightweight-charts v5 does not natively support vertical lines.
  // We approximate it as a price level marker (horizontal tick) using a marker
  // with "circle" shape at the target time, which is the closest achievable
  // without implementing a full ISeriesPrimitive canvas renderer.

  useEffect(() => {
    const chart = chartRef.current;
    const candle = candleRef.current;
    if (!chart || !candle) return;

    // ---- Clean up ALL previous drawing series ----
    const dsMap = drawingSeriesRef.current;
    for (const seriesList of dsMap.values()) {
      for (const s of seriesList) {
        try { chart.removeSeries(s); } catch { /* ignore */ }
      }
    }
    dsMap.clear();

    // Clean up old price lines from hlines (stored in hlineSeriesRef for compatibility)
    for (const ref of hlineSeriesRef.current) {
      try { ref._series.removePriceLine(ref._priceLine); } catch { /* ignore */ }
    }
    hlineSeriesRef.current = [];

    // Clean up old fib/rect price lines stored on candle series
    // (tracked via a separate list in the drawing objects themselves — we re-render all)

    // Re-render text markers
    const markers: SeriesMarker<Time>[] = [];
    textMarkersRef.current = [];

    // ---- Render each drawing ----
    for (const d of drawings) {
      if (d.kind === "hline") {
        try {
          const pl = candle.createPriceLine({
            price: d.price, color: "#eab308", lineWidth: 1,
            lineStyle: 2, axisLabelVisible: true, title: "",
          });
          hlineSeriesRef.current.push({ _priceLine: pl, _series: candle });
        } catch { /* ignore */ }

      } else if (d.kind === "vline") {
        // Render as a named price-level marker at that time stamp
        // Use a small LineSeries at that time with a very small value range
        // that spans the entire visible price range — approximated via marker
        const marker: SeriesMarker<Time> = {
          time: d.time,
          position: "inBar",
          color: "#64748b",
          shape: "square",
          size: 0.5,
          text: "|",
        };
        markers.push(marker);

      } else if (d.kind === "trendline" || d.kind === "ray") {
        try {
          const color = d.kind === "ray" ? "#f97316" : "#3b82f6";
          const s = chart.addSeries(LineSeries, {
            color, lineWidth: 1, priceScaleId: "right",
            lastValueVisible: false, priceLineVisible: false,
          });
          const data: LineData[] = [
            { time: d.p1.time, value: d.p1.price },
            { time: d.p2.time, value: d.p2.price },
          ];
          s.setData(data);
          dsMap.set(d.id, [s]);
        } catch { /* ignore */ }

      } else if (d.kind === "fib") {
        const hiPrice = Math.max(d.p1.price, d.p2.price);
        const loPrice = Math.min(d.p1.price, d.p2.price);
        const range = hiPrice - loPrice;
        for (const level of FIB_LEVELS) {
          const price = hiPrice - range * level;
          const color = FIB_COLORS[level] ?? "#94a3b8";
          try {
            const pl = candle.createPriceLine({
              price, color, lineWidth: 1, lineStyle: 2,
              axisLabelVisible: true,
              title: `Fib ${(level * 100).toFixed(1)}%`,
            });
            hlineSeriesRef.current.push({ _priceLine: pl, _series: candle });
          } catch { /* ignore */ }
        }

      } else if (d.kind === "rect") {
        // Two horizontal lines at top and bottom
        const topPrice = Math.max(d.p1.price, d.p2.price);
        const botPrice = Math.min(d.p1.price, d.p2.price);
        for (const [price, title] of [[topPrice, "Rect Top"], [botPrice, "Rect Bot"]] as [number, string][]) {
          try {
            const pl = candle.createPriceLine({
              price, color: "#8b5cf6", lineWidth: 1, lineStyle: 1,
              axisLabelVisible: true, title,
            });
            hlineSeriesRef.current.push({ _priceLine: pl, _series: candle });
          } catch { /* ignore */ }
        }

      } else if (d.kind === "text") {
        const marker: SeriesMarker<Time> = {
          time: d.point.time,
          position: "atPriceMiddle",
          color: "#facc15",
          shape: "circle",
          size: 1,
          price: d.point.price,
          text: d.label,
        };
        markers.push(marker);
      }
    }

    // Apply all markers at once
    if (markersPluginRef.current) {
      try {
        markersPluginRef.current.setMarkers(markers);
        textMarkersRef.current = markers;
      } catch { /* ignore */ }
    }

    return () => {
      // Cleanup on re-render
      for (const seriesList of dsMap.values()) {
        for (const s of seriesList) {
          try { chart.removeSeries(s); } catch { /* ignore */ }
        }
      }
      dsMap.clear();
      for (const ref of hlineSeriesRef.current) {
        try { ref._series.removePriceLine(ref._priceLine); } catch { /* gone */ }
      }
      hlineSeriesRef.current = [];
    };
  }, [drawings]);

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

  // --- event handlers ------------------------------------------------------
  const handleSymbolSelect = useCallback((item: SymbolSearchResult) => {
    setSymbol(item.symbol);
    setExchange(item.exchange);
    setLtp(null);
    setChange(null);
    setChangePct(null);
    setLegend(null);
    setDrawings([]);
    setPendingPoint(null);
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
      // Clear pivot lines
      if (pivotRef.current.series && pivotRef.current.lines.length > 0) {
        for (const pl of pivotRef.current.lines) {
          try { pivotRef.current.series.removePriceLine(pl); } catch { /* ignore */ }
        }
        pivotRef.current.lines = [];
        pivotRef.current.series = null;
      }
    }
  }, []);

  const handleIntervalChange = useCallback((v: string) => {
    setInterval(v);
  }, []);

  const toggleDrawMode = useCallback((mode: DrawToolType) => {
    setDrawMode((prev) => {
      if (prev === mode) {
        setPendingPoint(null);
        return null;
      }
      setPendingPoint(null);
      return mode;
    });
  }, []);

  const clearAllDrawings = useCallback(() => {
    setDrawings([]);
    setPendingPoint(null);
  }, []);

  const undoLastDrawing = useCallback(() => {
    setDrawings((prev) => prev.slice(0, -1));
  }, []);

  const toggleIndicator = useCallback(
    (key: keyof IndicatorState, value: boolean) => {
      setIndicators((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const handleTextConfirm = useCallback(
    (text: string) => {
      if (!awaitingText) return;
      setDrawings((prev) => [
        ...prev,
        { kind: "text", id: uid(), point: awaitingText, label: text },
      ]);
      setAwaitingText(null);
    },
    [awaitingText],
  );

  const handleTextCancel = useCallback(() => {
    setAwaitingText(null);
  }, []);

  // --- derived display -----------------------------------------------------
  const isPositive = change == null ? null : change >= 0;
  const changeColor =
    change == null
      ? "text-text-secondary"
      : isPositive
        ? "text-profit"
        : "text-loss";

  // Count active indicators for badge (excludes volume as it's always "baseline")
  const activeIndicatorCount = (Object.keys(indicators) as (keyof IndicatorState)[])
    .filter((k) => k !== "showVolume" && indicators[k])
    .length;

  const drawingCount = drawings.length;

  const twoClickTools: DrawToolType[] = ["trendline", "ray", "fib", "rect"];
  const isTwoClickMode = drawMode !== null && twoClickTools.includes(drawMode);

  return (
    <div className="flex flex-col h-full w-full bg-surface-base overflow-hidden">

      {/* header row */}
      <div className="flex items-center justify-between px-2 py-1 bg-surface-base border-b border-border-default shrink-0">

        {/* Left: symbol search + symbol info */}
        <div className="flex items-center gap-3 min-w-0">
          <SymbolSearch onSelect={handleSymbolSelect} />

          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm font-heading font-semibold text-text-primary leading-none whitespace-nowrap">
              {symbol}
            </span>
            <span className="text-xs text-text-muted whitespace-nowrap">
              {exchange}
            </span>
            {ltp != null && (
              <span className="text-lg font-mono font-bold text-text-primary leading-none whitespace-nowrap">
                {formatPrice(ltp)}
              </span>
            )}
            {change != null && (
              <span
                className={`flex items-center gap-0.5 text-xs font-mono whitespace-nowrap ${changeColor}`}
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
              className="flex items-center gap-2 bg-surface-card rounded px-2 py-0.5"
            >
              <span className="text-xxs text-text-muted uppercase">O</span>
              <span className="text-xs font-mono text-text-primary">
                {formatPrice(legend.open)}
              </span>
              <span className="text-xxs text-text-muted uppercase">H</span>
              <span className="text-xs font-mono text-text-primary">
                {formatPrice(legend.high)}
              </span>
              <span className="text-xxs text-text-muted uppercase">L</span>
              <span className="text-xs font-mono text-text-primary">
                {formatPrice(legend.low)}
              </span>
              <span className="text-xxs text-text-muted uppercase">C</span>
              <span className="text-xs font-mono text-text-primary">
                {formatPrice(legend.close)}
              </span>
              {legend.volume != null && (
                <>
                  <span className="text-xxs text-text-muted uppercase">V</span>
                  <span className="text-xs font-mono text-text-primary">
                    {formatVolume(legend.volume)}
                  </span>
                </>
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
      <div className="flex items-center gap-1 px-2 py-0.5 bg-surface-base border-b border-border-default shrink-0 flex-wrap min-h-7">

        {/* Indicators dropdown */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-xs font-sans gap-1 text-text-secondary hover:text-text-primary"
            >
              <BarChart2 size={11} />
              Indicators
              {activeIndicatorCount > 0 && (
                <span className="ml-0.5 bg-accent text-white rounded-full min-w-[18px] h-[18px] flex items-center justify-center text-xxs leading-none">
                  {activeIndicatorCount}
                </span>
              )}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="start"
            className="w-56 bg-surface-card border-border-default text-text-primary"
          >
            {/* Overlays */}
            <DropdownMenuLabel className="text-xs text-text-muted uppercase tracking-wider px-2 py-1">
              Overlays
            </DropdownMenuLabel>
            <DropdownMenuCheckboxItem
              checked={indicators.showEMA20}
              onCheckedChange={(v) => toggleIndicator("showEMA20", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-blue-500 inline-block shrink-0" />
              EMA
              <PeriodInput value={periods.ema1} onChange={(v) => setPeriods((p) => ({ ...p, ema1: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showEMA50}
              onCheckedChange={(v) => toggleIndicator("showEMA50", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-amber-500 inline-block shrink-0" />
              EMA
              <PeriodInput value={periods.ema2} onChange={(v) => setPeriods((p) => ({ ...p, ema2: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showSMA}
              onCheckedChange={(v) => toggleIndicator("showSMA", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-cyan-500 inline-block shrink-0" />
              SMA
              <PeriodInput value={periods.sma} onChange={(v) => setPeriods((p) => ({ ...p, sma: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showWMA}
              onCheckedChange={(v) => toggleIndicator("showWMA", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-lime-500 inline-block shrink-0" />
              WMA
              <PeriodInput value={periods.wma} onChange={(v) => setPeriods((p) => ({ ...p, wma: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showBB}
              onCheckedChange={(v) => toggleIndicator("showBB", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-slate-400 inline-block shrink-0" />
              BB
              <PeriodInput value={periods.bbPeriod} onChange={(v) => setPeriods((p) => ({ ...p, bbPeriod: v }))} />
              <PeriodInput value={periods.bbMult} onChange={(v) => setPeriods((p) => ({ ...p, bbMult: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showSupertrend}
              onCheckedChange={(v) => toggleIndicator("showSupertrend", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-profit inline-block shrink-0" />
              Supertrend
              <PeriodInput value={periods.stPeriod} onChange={(v) => setPeriods((p) => ({ ...p, stPeriod: v }))} />
              <PeriodInput value={periods.stFactor} onChange={(v) => setPeriods((p) => ({ ...p, stFactor: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showVWAP}
              onCheckedChange={(v) => toggleIndicator("showVWAP", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-fuchsia-400 inline-block shrink-0" />
              VWAP
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showIchimoku}
              onCheckedChange={(v) => toggleIndicator("showIchimoku", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-profit inline-block shrink-0" />
              Ichimoku Cloud
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showPivot}
              onCheckedChange={(v) => toggleIndicator("showPivot", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-slate-400 inline-block shrink-0" />
              Pivot Points
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showDEMA}
              onCheckedChange={(v) => toggleIndicator("showDEMA", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-orange-500 inline-block shrink-0" />
              DEMA
              <PeriodInput value={periods.dema} onChange={(v) => setPeriods((p) => ({ ...p, dema: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showHullMA}
              onCheckedChange={(v) => toggleIndicator("showHullMA", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-purple-500 inline-block shrink-0" />
              Hull MA
              <PeriodInput value={periods.hull} onChange={(v) => setPeriods((p) => ({ ...p, hull: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showParabolicSAR}
              onCheckedChange={(v) => toggleIndicator("showParabolicSAR", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-yellow-400 inline-block shrink-0" />
              Parabolic SAR
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showKeltner}
              onCheckedChange={(v) => toggleIndicator("showKeltner", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-orange-500 inline-block shrink-0" />
              Keltner
              <PeriodInput value={periods.keltner} onChange={(v) => setPeriods((p) => ({ ...p, keltner: v }))} />
              <PeriodInput value={periods.keltnerMult} onChange={(v) => setPeriods((p) => ({ ...p, keltnerMult: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showVWMA}
              onCheckedChange={(v) => toggleIndicator("showVWMA", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-teal-400 inline-block shrink-0" />
              VWMA
              <PeriodInput value={periods.vwma} onChange={(v) => setPeriods((p) => ({ ...p, vwma: v }))} />
            </DropdownMenuCheckboxItem>

            <DropdownMenuSeparator className="bg-border-default" />
            {/* Volume */}
            <DropdownMenuLabel className="text-xs text-text-muted uppercase tracking-wider px-2 py-1">
              Volume
            </DropdownMenuLabel>
            <DropdownMenuCheckboxItem
              checked={indicators.showVolume}
              onCheckedChange={(v) => toggleIndicator("showVolume", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-slate-500 inline-block shrink-0" />
              Volume
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showOBV}
              onCheckedChange={(v) => toggleIndicator("showOBV", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-slate-400 inline-block shrink-0" />
              OBV
            </DropdownMenuCheckboxItem>

            <DropdownMenuSeparator className="bg-border-default" />
            {/* Oscillators */}
            <DropdownMenuLabel className="text-xs text-text-muted uppercase tracking-wider px-2 py-1">
              Oscillators
            </DropdownMenuLabel>
            <DropdownMenuCheckboxItem
              checked={indicators.showRSI}
              onCheckedChange={(v) => toggleIndicator("showRSI", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-purple-500 inline-block shrink-0" />
              RSI
              <PeriodInput value={periods.rsi} onChange={(v) => setPeriods((p) => ({ ...p, rsi: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showMACD}
              onCheckedChange={(v) => toggleIndicator("showMACD", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-blue-500 inline-block shrink-0" />
              MACD (12, 26, 9)
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showStoch}
              onCheckedChange={(v) => toggleIndicator("showStoch", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-orange-500 inline-block shrink-0" />
              Stochastic (14, 3, 3)
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showATR}
              onCheckedChange={(v) => toggleIndicator("showATR", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-orange-400 inline-block shrink-0" />
              ATR
              <PeriodInput value={periods.atr} onChange={(v) => setPeriods((p) => ({ ...p, atr: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showADX}
              onCheckedChange={(v) => toggleIndicator("showADX", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-amber-400 inline-block shrink-0" />
              ADX
              <PeriodInput value={periods.adx} onChange={(v) => setPeriods((p) => ({ ...p, adx: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showWilliamsR}
              onCheckedChange={(v) => toggleIndicator("showWilliamsR", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-pink-400 inline-block shrink-0" />
              Williams %R
              <PeriodInput value={periods.wr} onChange={(v) => setPeriods((p) => ({ ...p, wr: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={indicators.showCCI}
              onCheckedChange={(v) => toggleIndicator("showCCI", v)}
              className="text-xs gap-2"
            >
              <span className="w-2 h-2 rounded-full bg-sky-400 inline-block shrink-0" />
              CCI
              <PeriodInput value={periods.cci} onChange={(v) => setPeriods((p) => ({ ...p, cci: v }))} />
            </DropdownMenuCheckboxItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <div className="w-px h-4 bg-border-default mx-0.5" />

        {/* Draw tools */}
        <span className="text-xxs text-text-muted uppercase tracking-wider mr-0.5">
          Draw
        </span>

        <DrawToolBtn toolId="hline" active={drawMode} onClick={toggleDrawMode} title="Horizontal line — click price level">
          <Minus size={11} />
          <span>H-Line</span>
        </DrawToolBtn>

        <DrawToolBtn toolId="vline" active={drawMode} onClick={toggleDrawMode} title="Vertical line — click bar">
          <AlignJustify size={11} style={{ transform: "rotate(90deg)" }} />
          <span>V-Line</span>
        </DrawToolBtn>

        <DrawToolBtn toolId="trendline" active={drawMode} onClick={toggleDrawMode} title="Trend line — click two points">
          <TrendingUp size={11} />
          <span>Trend</span>
        </DrawToolBtn>

        <DrawToolBtn toolId="ray" active={drawMode} onClick={toggleDrawMode} title="Ray — click origin + direction">
          <Move size={11} />
          <span>Ray</span>
        </DrawToolBtn>

        <DrawToolBtn toolId="fib" active={drawMode} onClick={toggleDrawMode} title="Fibonacci retracement — click high + low">
          <Triangle size={11} />
          <span>Fib</span>
        </DrawToolBtn>

        <DrawToolBtn toolId="rect" active={drawMode} onClick={toggleDrawMode} title="Rectangle — click two corners">
          <Square size={11} />
          <span>Rect</span>
        </DrawToolBtn>

        <DrawToolBtn toolId="text" active={drawMode} onClick={toggleDrawMode} title="Text annotation — click to place">
          <Type size={11} />
          <span>Text</span>
        </DrawToolBtn>

        {drawingCount > 0 && (
          <>
            <div className="w-px h-4 bg-border-default mx-0.5" />
            <button
              onClick={undoLastDrawing}
              title="Undo last drawing"
              className="flex items-center gap-1 px-2 py-1 rounded text-xs text-text-secondary hover:text-loss hover:bg-surface-hover transition-colors"
            >
              <X size={10} />
              <span>Undo</span>
            </button>
            {drawingCount > 1 && (
              <button
                onClick={clearAllDrawings}
                title="Clear all drawings"
                className="flex items-center gap-1 px-2 py-1 rounded text-xs text-text-secondary hover:text-loss hover:bg-surface-hover transition-colors"
              >
                <Trash2 size={10} />
                <span>Clear</span>
              </button>
            )}
            <span className="text-xxs text-text-muted ml-auto">
              {drawingCount} drawing{drawingCount !== 1 ? "s" : ""}
            </span>
          </>
        )}

        {/* Status hints */}
        {drawMode !== null && !isTwoClickMode && (
          <span className="text-xxs text-accent ml-1 animate-pulse">
            Click chart to place
          </span>
        )}
        {isTwoClickMode && pendingPoint === null && (
          <span className="text-xxs text-accent ml-1 animate-pulse">
            Click first point
          </span>
        )}
        {isTwoClickMode && pendingPoint !== null && (
          <span className="text-xxs text-accent ml-1 animate-pulse">
            Click second point
          </span>
        )}
        {drawMode === "text" && awaitingText !== null && (
          <span className="text-xxs text-accent ml-1 animate-pulse">
            Type text below
          </span>
        )}
      </div>

      {/* chart area — relative so text overlay can be positioned inside */}
      <div className="flex-1 w-full min-h-0 relative">
        <div
          ref={containerRef}
          className="w-full h-full"
          style={{
            cursor: drawMode !== null ? "crosshair" : "default",
          }}
        />
        {/* Text annotation input overlay */}
        {awaitingText !== null && (
          <TextInputOverlay
            onConfirm={handleTextConfirm}
            onCancel={handleTextCancel}
          />
        )}
      </div>
    </div>
  );
}
