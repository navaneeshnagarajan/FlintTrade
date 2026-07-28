// Shared types for the Chart widget and its sub-modules.
// Import from here rather than re-declaring across files.

import type { ISeriesApi, IPriceLine, Time } from "lightweight-charts";
import type {
  FlintChartDrawing,
  FlintChartDrawingPoint,
  FlintChartDrawToolId,
  FlintChartIndicatorPeriods,
  FlintChartIndicatorState,
} from "@flinttrade/design-system";

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

export type DrawToolType = FlintChartDrawToolId;

export type DrawingPoint = FlintChartDrawingPoint<Time>;
export type Drawing = FlintChartDrawing<Time>;

// ---------------------------------------------------------------------------
// Indicator toggles and periods
// ---------------------------------------------------------------------------

export type IndicatorState = FlintChartIndicatorState;
export type IndicatorPeriods = FlintChartIndicatorPeriods;

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
  // Server-computed tier (data from POST /api/v1/indicators/compute)
  kama: ISeriesApi<"Line"> | null;
  alma: ISeriesApi<"Line"> | null;
  donUpper: ISeriesApi<"Line"> | null;
  donMiddle: ISeriesApi<"Line"> | null;
  donLower: ISeriesApi<"Line"> | null;
  chandLong: ISeriesApi<"Line"> | null;
  chandShort: ISeriesApi<"Line"> | null;
  stochRsiK: ISeriesApi<"Line"> | null;
  stochRsiD: ISeriesApi<"Line"> | null;
  mfi: ISeriesApi<"Line"> | null;
  squeezeHist: ISeriesApi<"Histogram"> | null;
  aoHist: ISeriesApi<"Histogram"> | null;
  tema: ISeriesApi<"Line"> | null;
  t3: ISeriesApi<"Line"> | null;
  trima: ISeriesApi<"Line"> | null;
  mcginley: ISeriesApi<"Line"> | null;
  maeUpper: ISeriesApi<"Line"> | null;
  maeMiddle: ISeriesApi<"Line"> | null;
  maeLower: ISeriesApi<"Line"> | null;
  starcUpper: ISeriesApi<"Line"> | null;
  starcMiddle: ISeriesApi<"Line"> | null;
  starcLower: ISeriesApi<"Line"> | null;
  cmf: ISeriesApi<"Line"> | null;
  roc: ISeriesApi<"Line"> | null;
  mom: ISeriesApi<"Line"> | null;
  trix: ISeriesApi<"Line"> | null;
  chop: ISeriesApi<"Line"> | null;
  hv: ISeriesApi<"Line"> | null;
  vortexPlus: ISeriesApi<"Line"> | null;
  vortexMinus: ISeriesApi<"Line"> | null;
  fisher: ISeriesApi<"Line"> | null;
  fisherSignal: ISeriesApi<"Line"> | null;
  kstLine: ISeriesApi<"Line"> | null;
  kstSignal: ISeriesApi<"Line"> | null;
  coppock: ISeriesApi<"Line"> | null;
  ad: ISeriesApi<"Line"> | null;
  pvt: ISeriesApi<"Line"> | null;
}

export interface HlineRef {
  _key: string;
  _priceLine: IPriceLine;
  _series: ISeriesApi<"Candlestick">;
}

export interface PivotRefs {
  lines: IPriceLine[];
  series: ISeriesApi<"Candlestick"> | null;
}

export type DrawingSeriesMap = Map<string, ISeriesApi<"Line">>;
