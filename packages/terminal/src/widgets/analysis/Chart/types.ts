// Shared types for the Chart widget and its sub-modules.
// Import from here rather than re-declaring across files.

import type { ISeriesApi, IPriceLine, Time } from "lightweight-charts";

// ---------------------------------------------------------------------------
// Symbol / interval
// ---------------------------------------------------------------------------

export interface SymbolSearchResult {
  symbol: string;
  exchange: string;
  name?: string;
  instrument_type?: string;
}

export interface IntervalOption {
  label: string;
  value: string;
}

// ---------------------------------------------------------------------------
// Drawing tools
// ---------------------------------------------------------------------------

export type DrawToolType =
  | "hline"
  | "vline"
  | "trendline"
  | "ray"
  | "fib"
  | "rect"
  | "text";

export interface DrawingPoint {
  time: Time;
  price: number;
}

export interface HLineDrawing  { kind: "hline";     id: string; price: number }
export interface VLineDrawing  { kind: "vline";     id: string; time: Time }
export interface TrendLineDrawing { kind: "trendline"; id: string; p1: DrawingPoint; p2: DrawingPoint }
export interface RayDrawing    { kind: "ray";       id: string; p1: DrawingPoint; p2: DrawingPoint }
export interface FibDrawing    { kind: "fib";       id: string; p1: DrawingPoint; p2: DrawingPoint }
export interface RectDrawing   { kind: "rect";      id: string; p1: DrawingPoint; p2: DrawingPoint }
export interface TextDrawing   { kind: "text";      id: string; point: DrawingPoint; label: string }

export type Drawing =
  | HLineDrawing
  | VLineDrawing
  | TrendLineDrawing
  | RayDrawing
  | FibDrawing
  | RectDrawing
  | TextDrawing;

// ---------------------------------------------------------------------------
// Indicator toggles and periods
// ---------------------------------------------------------------------------

export interface IndicatorState {
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
  showWilliamsR: boolean;
  showCCI: boolean;
  showDEMA: boolean;
  showHullMA: boolean;
  showParabolicSAR: boolean;
  showOBV: boolean;
  showKeltner: boolean;
  showVWMA: boolean;
}

export interface IndicatorPeriods {
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

// ---------------------------------------------------------------------------
// Chart series refs
// ---------------------------------------------------------------------------

export interface IndicatorSeriesRefs {
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

export interface HlineRef {
  _priceLine: IPriceLine;
  _series: ISeriesApi<"Candlestick">;
}

export interface PivotRefs {
  lines: IPriceLine[];
  series: ISeriesApi<"Candlestick"> | null;
}

export type DrawingSeriesMap = Map<string, ISeriesApi<"Line">[]>;
