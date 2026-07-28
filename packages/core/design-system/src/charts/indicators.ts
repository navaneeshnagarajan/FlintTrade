import type { PivotResult } from "./calculations"
import type { FlintChartPriceLineSpec } from "./drawings"

export const FLINT_CHART_INDICATOR_CATEGORIES = ["Overlays", "Volume", "Oscillators"] as const

export type FlintChartIndicatorCategory = (typeof FLINT_CHART_INDICATOR_CATEGORIES)[number]

export type FlintChartIndicatorKey =
  | "showEMA20"
  | "showEMA50"
  | "showSMA"
  | "showWMA"
  | "showBB"
  | "showSupertrend"
  | "showVWAP"
  | "showIchimoku"
  | "showPivot"
  | "showVolume"
  | "showRSI"
  | "showMACD"
  | "showStoch"
  | "showATR"
  | "showADX"
  | "showWilliamsR"
  | "showCCI"
  | "showDEMA"
  | "showHullMA"
  | "showParabolicSAR"
  | "showOBV"
  | "showKeltner"
  | "showVWMA"
  | "showOI"
  // Server-computed tier — series fetched from POST /api/v1/indicators/compute
  | "showKAMA"
  | "showALMA"
  | "showDonchian"
  | "showChandelier"
  | "showStochRSI"
  | "showMFI"
  | "showSqueeze"
  | "showAO"

export interface FlintChartIndicatorState {
  showEMA20: boolean
  showEMA50: boolean
  showSMA: boolean
  showWMA: boolean
  showBB: boolean
  showSupertrend: boolean
  showVWAP: boolean
  showIchimoku: boolean
  showPivot: boolean
  showVolume: boolean
  showRSI: boolean
  showMACD: boolean
  showStoch: boolean
  showATR: boolean
  showADX: boolean
  showWilliamsR: boolean
  showCCI: boolean
  showDEMA: boolean
  showHullMA: boolean
  showParabolicSAR: boolean
  showOBV: boolean
  showKeltner: boolean
  showVWMA: boolean
  showOI: boolean
  showKAMA: boolean
  showALMA: boolean
  showDonchian: boolean
  showChandelier: boolean
  showStochRSI: boolean
  showMFI: boolean
  showSqueeze: boolean
  showAO: boolean
}

export type FlintChartIndicatorPeriodKey =
  | "ema1"
  | "ema2"
  | "sma"
  | "wma"
  | "bbPeriod"
  | "bbMult"
  | "stPeriod"
  | "stFactor"
  | "rsi"
  | "cci"
  | "dema"
  | "hull"
  | "wr"
  | "keltner"
  | "keltnerMult"
  | "vwma"
  | "atr"
  | "adx"
  | "kama"
  | "alma"
  | "donchian"
  | "chand"
  | "stochRsi"
  | "mfi"

export interface FlintChartIndicatorPeriods {
  ema1: number
  ema2: number
  sma: number
  wma: number
  bbPeriod: number
  bbMult: number
  stPeriod: number
  stFactor: number
  rsi: number
  cci: number
  dema: number
  hull: number
  wr: number
  keltner: number
  keltnerMult: number
  vwma: number
  atr: number
  adx: number
  kama: number
  alma: number
  donchian: number
  chand: number
  stochRsi: number
  mfi: number
}

export type FlintChartIndicatorColor = (typeof FLINT_CHART_INDICATOR_PALETTE)[number]
export type FlintChartIndicatorLineStyle = "solid" | "dashed" | "dotted"

export interface FlintChartIndicatorPeriodControl {
  field: FlintChartIndicatorPeriodKey
  label: string
  min: number
  max: number
  step: number
}

export interface FlintChartIndicatorDefinition {
  key: FlintChartIndicatorKey
  name: string
  description: string
  category: FlintChartIndicatorCategory
  defaultColor: FlintChartIndicatorColor
  periods: readonly FlintChartIndicatorPeriodControl[]
  hasLineStyle: boolean
  priceScaleId: "right" | "vol" | "rsi" | "macd" | "stoch" | "atr" | "adx" | "wr" | "cci" | "obv" | "oi" | "stochrsi" | "mfi" | "squeeze" | "ao"
}

export interface FlintChartIndicatorPaneSpec {
  scaleId: string
  scaleMargins: {
    top: number
    bottom: number
  }
  borderVisible?: boolean
}

export interface FlintChartIndicatorLifecyclePlan {
  activeDefinitions: readonly FlintChartIndicatorDefinition[]
  activeKeys: readonly FlintChartIndicatorKey[]
  activePriceScaleIds: readonly string[]
  paneSpecs: readonly FlintChartIndicatorPaneSpec[]
  volumeVisible: boolean
}

export interface FlintChartIndicatorPaneLayoutSpec extends FlintChartIndicatorPaneSpec {
  paneIndex: number
  stretchFactor: number
}

export interface FlintChartIndicatorPaneLayoutPlan {
  mainPaneIndex: 0
  mainPaneStretchFactor: number
  panes: readonly FlintChartIndicatorPaneLayoutSpec[]
  paneIndexByScaleId: Readonly<Record<string, number>>
}

export type FlintChartIndicatorPaneSize = "compact" | "balanced" | "expanded"

export type FlintChartIndicatorPaneSizes = Record<string, FlintChartIndicatorPaneSize>
export type FlintChartIndicatorPaneStretchFactors = Record<string, number>

export interface FlintChartIndicatorPaneControl {
  scaleId: string
  label: string
  size: FlintChartIndicatorPaneSize
  stretchFactor: number
  isCustomSize: boolean
}

export interface FlintChartIndicatorPaneResizeInput {
  paneStretchFactors?: FlintChartIndicatorPaneStretchFactors
  scaleId: string
  startStretchFactor: number
  deltaPixels: number
  pixelsPerStretchFactor?: number
}

export type FlintChartIndicatorLineWidth = 1 | 2 | 3 | 4

export interface FlintChartIndicatorLineSeriesOptions {
  color: string
  lineStyle: 0 | 1 | 2
  lineWidth: FlintChartIndicatorLineWidth
  priceScaleId: string
  title: string
  lastValueVisible: boolean
  priceLineVisible: boolean
  pointMarkersVisible?: boolean
}

export interface FlintChartIndicatorLineSeriesOptionsInput {
  key?: FlintChartIndicatorKey
  title: string
  color?: string
  lineStyle?: FlintChartIndicatorLineStyle | 0 | 1 | 2
  lineWidth?: FlintChartIndicatorLineWidth
  priceScaleId?: string
  lastValueVisible?: boolean
  priceLineVisible?: boolean
  pointMarkersVisible?: boolean
}

export interface FlintChartIndicatorHistogramSeriesOptions {
  priceScaleId: string
  title: string
  lastValueVisible: boolean
  priceLineVisible: boolean
}

export interface FlintChartIndicatorHistogramSeriesOptionsInput {
  title: string
  priceScaleId?: string
  lastValueVisible?: boolean
  priceLineVisible?: boolean
}

export type FlintChartIndicatorSeriesRefKey =
  | "ema20"
  | "ema50"
  | "sma"
  | "wma"
  | "bbUpper"
  | "bbMiddle"
  | "bbLower"
  | "stUp"
  | "stDown"
  | "vwap"
  | "ichTenkan"
  | "ichKijun"
  | "ichSenkouA"
  | "ichSenkouB"
  | "ichChikou"
  | "rsi"
  | "macdHist"
  | "macdLine"
  | "macdSignal"
  | "stochK"
  | "stochD"
  | "atr"
  | "adx"
  | "adxPlus"
  | "adxMinus"
  | "williamsR"
  | "cci"
  | "dema"
  | "hullMA"
  | "parSar"
  | "obv"
  | "keltnerUpper"
  | "keltnerMiddle"
  | "keltnerLower"
  | "vwma"
  | "kama"
  | "alma"
  | "donUpper"
  | "donMiddle"
  | "donLower"
  | "chandLong"
  | "chandShort"
  | "stochRsiK"
  | "stochRsiD"
  | "mfi"
  | "squeezeHist"
  | "aoHist"

interface FlintChartIndicatorSeriesRenderSpecBase {
  key: string
  indicatorKey: FlintChartIndicatorKey
  refKey: FlintChartIndicatorSeriesRefKey
  paneScaleId: string
  paneIndex?: number
}

export interface FlintChartIndicatorLineSeriesRenderSpec extends FlintChartIndicatorSeriesRenderSpecBase {
  options: FlintChartIndicatorLineSeriesOptions
}

export interface FlintChartIndicatorHistogramSeriesRenderSpec extends FlintChartIndicatorSeriesRenderSpecBase {
  options: FlintChartIndicatorHistogramSeriesOptions
}

export interface FlintChartIndicatorSeriesRenderPlanInput {
  indicators: FlintChartIndicatorState
  periods: FlintChartIndicatorPeriods
  colors?: Partial<Record<FlintChartIndicatorKey, FlintChartIndicatorColor>>
  lineStyles?: Partial<Record<FlintChartIndicatorKey, FlintChartIndicatorLineStyle>>
  paneSizes?: FlintChartIndicatorPaneSizes
  paneStretchFactors?: FlintChartIndicatorPaneStretchFactors
}

export interface FlintChartIndicatorSeriesRenderPlan {
  lifecyclePlan: FlintChartIndicatorLifecyclePlan
  paneLayoutPlan: FlintChartIndicatorPaneLayoutPlan
  lineSeries: FlintChartIndicatorLineSeriesRenderSpec[]
  histogramSeries: FlintChartIndicatorHistogramSeriesRenderSpec[]
}

export interface FlintChartIndicatorSeriesRenderPlanPartDiff<TSpec> {
  added: TSpec[]
  updated: TSpec[]
  unchanged: TSpec[]
  removed: TSpec[]
}

export interface FlintChartIndicatorSeriesRenderPlanDiff {
  lineSeries: FlintChartIndicatorSeriesRenderPlanPartDiff<FlintChartIndicatorLineSeriesRenderSpec>
  histogramSeries: FlintChartIndicatorSeriesRenderPlanPartDiff<FlintChartIndicatorHistogramSeriesRenderSpec>
}

export interface FlintChartOIOverlaySeriesOptions {
  color: string
  priceFormat: { type: "volume" }
  priceScaleId: "oi"
}

export interface FlintChartOIProfileBarDataInput<TTime = unknown> {
  latestTime: TTime
  totalCeOi: number
  totalPeOi: number
}

export interface FlintChartOIProfileBarData<TTime = unknown> {
  time: TTime
  value: number
  color: string
}

export interface FlintChartIndicatorSettings {
  version: 1
  indicators: FlintChartIndicatorState
  periods: FlintChartIndicatorPeriods
  colors: Record<FlintChartIndicatorKey, FlintChartIndicatorColor>
  lineStyles: Record<FlintChartIndicatorKey, FlintChartIndicatorLineStyle>
  paneSizes: FlintChartIndicatorPaneSizes
  paneStretchFactors: FlintChartIndicatorPaneStretchFactors
  updatedAt: number
}

export interface FlintChartIndicatorSettingsInput {
  indicators: FlintChartIndicatorState
  periods: FlintChartIndicatorPeriods
  colors: Record<FlintChartIndicatorKey, FlintChartIndicatorColor>
  lineStyles: Record<FlintChartIndicatorKey, FlintChartIndicatorLineStyle>
  paneSizes?: FlintChartIndicatorPaneSizes
  paneStretchFactors?: FlintChartIndicatorPaneStretchFactors
}

export const FLINT_CHART_INDICATOR_SETTINGS_STORAGE_KEY = "flinttrade:chart:indicator-settings:v1"
export const FLINT_CHART_INDICATOR_SETTINGS_VERSION = 1

export const FLINT_CHART_DEFAULT_INDICATORS: FlintChartIndicatorState = {
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
  showWilliamsR: false,
  showCCI: false,
  showDEMA: false,
  showHullMA: false,
  showParabolicSAR: false,
  showOBV: false,
  showKeltner: false,
  showVWMA: false,
  showOI: false,
  showKAMA: false,
  showALMA: false,
  showDonchian: false,
  showChandelier: false,
  showStochRSI: false,
  showMFI: false,
  showSqueeze: false,
  showAO: false,
}

export const FLINT_CHART_DEFAULT_PERIODS: FlintChartIndicatorPeriods = {
  ema1: 20,
  ema2: 50,
  sma: 20,
  wma: 20,
  bbPeriod: 20,
  bbMult: 2,
  stPeriod: 10,
  stFactor: 3,
  rsi: 14,
  cci: 20,
  dema: 20,
  hull: 20,
  wr: 14,
  keltner: 20,
  keltnerMult: 2.0,
  vwma: 20,
  atr: 14,
  adx: 14,
  kama: 10,
  alma: 9,
  donchian: 20,
  chand: 22,
  stochRsi: 14,
  mfi: 14,
}

export const FLINT_CHART_INDICATOR_PALETTE = [
  "#3b82f6",
  "#f59e0b",
  "#06b6d4",
  "#84cc16",
  "#94a3b8",
  "#22c55e",
  "#a855f7",
  "#f97316",
  "#ec4899",
  "#ef4444",
  "#14b8a6",
  "#6366f1",
  "#fbbf24",
  "#38bdf8",
  "#fb923c",
  "#e879f9",
] as const

export const FLINT_CHART_INDICATOR_DEFINITIONS: readonly FlintChartIndicatorDefinition[] = [
  {
    key: "showEMA20",
    name: "EMA",
    description: "Exponential Moving Average - weights recent prices more heavily.",
    category: "Overlays",
    defaultColor: "#3b82f6",
    periods: [{ field: "ema1", label: "Period", min: 2, max: 500, step: 1 }],
    hasLineStyle: true,
    priceScaleId: "right",
  },
  {
    key: "showEMA50",
    name: "EMA (2)",
    description: "Second EMA line with an independent period.",
    category: "Overlays",
    defaultColor: "#f59e0b",
    periods: [{ field: "ema2", label: "Period", min: 2, max: 500, step: 1 }],
    hasLineStyle: true,
    priceScaleId: "right",
  },
  {
    key: "showSMA",
    name: "SMA",
    description: "Simple Moving Average - equal weight on all periods.",
    category: "Overlays",
    defaultColor: "#06b6d4",
    periods: [{ field: "sma", label: "Period", min: 2, max: 500, step: 1 }],
    hasLineStyle: true,
    priceScaleId: "right",
  },
  {
    key: "showWMA",
    name: "WMA",
    description: "Weighted Moving Average - linear weight increase.",
    category: "Overlays",
    defaultColor: "#84cc16",
    periods: [{ field: "wma", label: "Period", min: 2, max: 500, step: 1 }],
    hasLineStyle: true,
    priceScaleId: "right",
  },
  {
    key: "showDEMA",
    name: "DEMA",
    description: "Double Exponential Moving Average - reduces lag further than EMA.",
    category: "Overlays",
    defaultColor: "#f97316",
    periods: [{ field: "dema", label: "Period", min: 2, max: 500, step: 1 }],
    hasLineStyle: true,
    priceScaleId: "right",
  },
  {
    key: "showHullMA",
    name: "Hull MA",
    description: "Hull Moving Average - fast, smooth, and responsive.",
    category: "Overlays",
    defaultColor: "#a855f7",
    periods: [{ field: "hull", label: "Period", min: 2, max: 500, step: 1 }],
    hasLineStyle: true,
    priceScaleId: "right",
  },
  {
    key: "showVWMA",
    name: "VWMA",
    description: "Volume-Weighted Moving Average.",
    category: "Overlays",
    defaultColor: "#14b8a6",
    periods: [{ field: "vwma", label: "Period", min: 2, max: 200, step: 1 }],
    hasLineStyle: true,
    priceScaleId: "right",
  },
  {
    key: "showKAMA",
    name: "KAMA",
    description: "Kaufman Adaptive Moving Average - adapts smoothing to market noise. Computed server-side.",
    category: "Overlays",
    defaultColor: "#e879f9",
    periods: [{ field: "kama", label: "Period", min: 2, max: 200, step: 1 }],
    hasLineStyle: true,
    priceScaleId: "right",
  },
  {
    key: "showALMA",
    name: "ALMA",
    description: "Arnaud Legoux Moving Average - Gaussian-weighted, low lag. Computed server-side.",
    category: "Overlays",
    defaultColor: "#f59e0b",
    periods: [{ field: "alma", label: "Period", min: 2, max: 200, step: 1 }],
    hasLineStyle: true,
    priceScaleId: "right",
  },
  {
    key: "showDonchian",
    name: "Donchian Channels",
    description: "Highest-high / lowest-low channel with midline. Computed server-side.",
    category: "Overlays",
    defaultColor: "#38bdf8",
    periods: [{ field: "donchian", label: "Period", min: 2, max: 200, step: 1 }],
    hasLineStyle: false,
    priceScaleId: "right",
  },
  {
    key: "showChandelier",
    name: "Chandelier Exit",
    description: "ATR-based trailing stop lines for long and short. Computed server-side.",
    category: "Overlays",
    defaultColor: "#ec4899",
    periods: [{ field: "chand", label: "Period", min: 2, max: 100, step: 1 }],
    hasLineStyle: false,
    priceScaleId: "right",
  },
  {
    key: "showBB",
    name: "Bollinger Bands",
    description: "Volatility envelope: SMA +/- N standard deviations.",
    category: "Overlays",
    defaultColor: "#94a3b8",
    periods: [
      { field: "bbPeriod", label: "Period", min: 2, max: 200, step: 1 },
      { field: "bbMult", label: "Mult", min: 0.5, max: 5, step: 0.1 },
    ],
    hasLineStyle: true,
    priceScaleId: "right",
  },
  {
    key: "showKeltner",
    name: "Keltner Channel",
    description: "ATR-based channel around an EMA.",
    category: "Overlays",
    defaultColor: "#f97316",
    periods: [
      { field: "keltner", label: "Period", min: 2, max: 200, step: 1 },
      { field: "keltnerMult", label: "Mult", min: 0.5, max: 5, step: 0.1 },
    ],
    hasLineStyle: true,
    priceScaleId: "right",
  },
  {
    key: "showSupertrend",
    name: "Supertrend",
    description: "ATR-based trailing stop and trend direction indicator.",
    category: "Overlays",
    defaultColor: "#22c55e",
    periods: [
      { field: "stPeriod", label: "Period", min: 2, max: 100, step: 1 },
      { field: "stFactor", label: "Factor", min: 1, max: 10, step: 0.5 },
    ],
    hasLineStyle: false,
    priceScaleId: "right",
  },
  {
    key: "showVWAP",
    name: "VWAP",
    description: "Volume-Weighted Average Price - intraday benchmark.",
    category: "Overlays",
    defaultColor: "#e879f9",
    periods: [],
    hasLineStyle: true,
    priceScaleId: "right",
  },
  {
    key: "showIchimoku",
    name: "Ichimoku Cloud",
    description: "Multi-line Japanese trend and support/resistance system.",
    category: "Overlays",
    defaultColor: "#22c55e",
    periods: [],
    hasLineStyle: false,
    priceScaleId: "right",
  },
  {
    key: "showPivot",
    name: "Pivot Points",
    description: "Daily pivot, R1-R3, S1-S3 price levels.",
    category: "Overlays",
    defaultColor: "#94a3b8",
    periods: [],
    hasLineStyle: true,
    priceScaleId: "right",
  },
  {
    key: "showParabolicSAR",
    name: "Parabolic SAR",
    description: "Stop-and-reverse trend-following dots.",
    category: "Overlays",
    defaultColor: "#fbbf24",
    periods: [],
    hasLineStyle: false,
    priceScaleId: "right",
  },
  {
    key: "showVolume",
    name: "Volume",
    description: "Bar volume histogram on a separate price scale.",
    category: "Volume",
    defaultColor: "#94a3b8",
    periods: [],
    hasLineStyle: false,
    priceScaleId: "vol",
  },
  {
    key: "showOBV",
    name: "OBV",
    description: "On-Balance Volume - cumulative volume flow indicator.",
    category: "Volume",
    defaultColor: "#94a3b8",
    periods: [],
    hasLineStyle: true,
    priceScaleId: "obv",
  },
  {
    key: "showOI",
    name: "OI Overlay",
    description: "Open Interest histogram overlay fetched from OpenAlgo-compatible data.",
    category: "Volume",
    defaultColor: "#6366f1",
    periods: [],
    hasLineStyle: false,
    priceScaleId: "oi",
  },
  {
    key: "showRSI",
    name: "RSI",
    description: "Relative Strength Index - overbought/oversold momentum from 0 to 100.",
    category: "Oscillators",
    defaultColor: "#a855f7",
    periods: [{ field: "rsi", label: "Period", min: 2, max: 100, step: 1 }],
    hasLineStyle: true,
    priceScaleId: "rsi",
  },
  {
    key: "showMACD",
    name: "MACD",
    description: "Moving Average Convergence Divergence (12, 26, 9).",
    category: "Oscillators",
    defaultColor: "#3b82f6",
    periods: [],
    hasLineStyle: false,
    priceScaleId: "macd",
  },
  {
    key: "showStoch",
    name: "Stochastic",
    description: "Stochastic oscillator K and D lines (14, 3, 3).",
    category: "Oscillators",
    defaultColor: "#f97316",
    periods: [],
    hasLineStyle: true,
    priceScaleId: "stoch",
  },
  {
    key: "showATR",
    name: "ATR",
    description: "Average True Range - measures market volatility.",
    category: "Oscillators",
    defaultColor: "#fb923c",
    periods: [{ field: "atr", label: "Period", min: 2, max: 100, step: 1 }],
    hasLineStyle: true,
    priceScaleId: "atr",
  },
  {
    key: "showADX",
    name: "ADX",
    description: "Average Directional Index - trend strength from 0 to 100.",
    category: "Oscillators",
    defaultColor: "#fbbf24",
    periods: [{ field: "adx", label: "Period", min: 2, max: 100, step: 1 }],
    hasLineStyle: true,
    priceScaleId: "adx",
  },
  {
    key: "showWilliamsR",
    name: "Williams %R",
    description: "Williams %R - momentum oscillator from -100 to 0.",
    category: "Oscillators",
    defaultColor: "#ec4899",
    periods: [{ field: "wr", label: "Period", min: 2, max: 100, step: 1 }],
    hasLineStyle: true,
    priceScaleId: "wr",
  },
  {
    key: "showCCI",
    name: "CCI",
    description: "Commodity Channel Index - deviation from average price.",
    category: "Oscillators",
    defaultColor: "#38bdf8",
    periods: [{ field: "cci", label: "Period", min: 2, max: 100, step: 1 }],
    hasLineStyle: true,
    priceScaleId: "cci",
  },
  {
    key: "showStochRSI",
    name: "Stoch RSI",
    description: "Stochastic oscillator applied to RSI - %K and %D lines. Computed server-side.",
    category: "Oscillators",
    defaultColor: "#06b6d4",
    periods: [{ field: "stochRsi", label: "RSI period", min: 2, max: 100, step: 1 }],
    hasLineStyle: true,
    priceScaleId: "stochrsi",
  },
  {
    key: "showMFI",
    name: "MFI",
    description: "Money Flow Index - volume-weighted RSI from 0 to 100. Computed server-side.",
    category: "Oscillators",
    defaultColor: "#84cc16",
    periods: [{ field: "mfi", label: "Period", min: 2, max: 100, step: 1 }],
    hasLineStyle: true,
    priceScaleId: "mfi",
  },
  {
    key: "showSqueeze",
    name: "Squeeze Momentum",
    description: "Bollinger-inside-Keltner squeeze with momentum histogram. Computed server-side.",
    category: "Oscillators",
    defaultColor: "#94a3b8",
    periods: [],
    hasLineStyle: false,
    priceScaleId: "squeeze",
  },
  {
    key: "showAO",
    name: "Awesome Oscillator",
    description: "Median-price momentum histogram (5/34). Computed server-side.",
    category: "Oscillators",
    defaultColor: "#fb923c",
    periods: [],
    hasLineStyle: false,
    priceScaleId: "ao",
  },
] as const

export const FLINT_CHART_INDICATOR_DEFAULT_COLORS: Readonly<Record<FlintChartIndicatorKey, FlintChartIndicatorColor>> =
  Object.fromEntries(
    FLINT_CHART_INDICATOR_DEFINITIONS.map((definition) => [definition.key, definition.defaultColor]),
  ) as Record<FlintChartIndicatorKey, FlintChartIndicatorColor>

export const FLINT_CHART_INDICATOR_DEFAULT_LINE_STYLES: Readonly<
  Record<FlintChartIndicatorKey, FlintChartIndicatorLineStyle>
> = Object.fromEntries(
  FLINT_CHART_INDICATOR_DEFINITIONS.map((definition) => [definition.key, "solid" as FlintChartIndicatorLineStyle]),
) as Record<FlintChartIndicatorKey, FlintChartIndicatorLineStyle>

export const FLINT_CHART_INDICATOR_PANE_SPECS: Readonly<Record<string, FlintChartIndicatorPaneSpec>> = {
  rsi: { scaleId: "rsi", scaleMargins: { top: 0.75, bottom: 0.05 } },
  macd: { scaleId: "macd", scaleMargins: { top: 0.6, bottom: 0.05 } },
  stoch: { scaleId: "stoch", scaleMargins: { top: 0.65, bottom: 0.05 } },
  atr: { scaleId: "atr", scaleMargins: { top: 0.7, bottom: 0.05 } },
  adx: { scaleId: "adx", scaleMargins: { top: 0.65, bottom: 0.05 } },
  wr: { scaleId: "wr", scaleMargins: { top: 0.7, bottom: 0.05 } },
  cci: { scaleId: "cci", scaleMargins: { top: 0.7, bottom: 0.05 } },
  obv: { scaleId: "obv", scaleMargins: { top: 0.7, bottom: 0.05 } },
  oi: { scaleId: "oi", scaleMargins: { top: 0.75, bottom: 0 }, borderVisible: false },
  stochrsi: { scaleId: "stochrsi", scaleMargins: { top: 0.65, bottom: 0.05 } },
  mfi: { scaleId: "mfi", scaleMargins: { top: 0.75, bottom: 0.05 } },
  squeeze: { scaleId: "squeeze", scaleMargins: { top: 0.65, bottom: 0.05 } },
  ao: { scaleId: "ao", scaleMargins: { top: 0.65, bottom: 0.05 } },
}

export const FLINT_CHART_INDICATOR_PANE_SIZE_OPTIONS = ["compact", "balanced", "expanded"] as const

export const FLINT_CHART_INDICATOR_PANE_SIZE_LABELS: Readonly<Record<FlintChartIndicatorPaneSize, string>> = {
  compact: "Compact",
  balanced: "Balanced",
  expanded: "Expanded",
}

export const FLINT_CHART_INDICATOR_PANE_SIZE_SHORT_LABELS: Readonly<Record<FlintChartIndicatorPaneSize, string>> = {
  compact: "S",
  balanced: "M",
  expanded: "L",
}

export const FLINT_CHART_INDICATOR_PANE_STRETCH_FACTORS: Readonly<Record<FlintChartIndicatorPaneSize, number>> = {
  compact: 0.75,
  balanced: 1,
  expanded: 1.5,
}

export const FLINT_CHART_INDICATOR_PANE_STRETCH_FACTOR_MIN = 0.5
export const FLINT_CHART_INDICATOR_PANE_STRETCH_FACTOR_MAX = 2.5
export const FLINT_CHART_INDICATOR_PANE_RESIZE_PIXELS_PER_STRETCH_FACTOR = 200

export const FLINT_CHART_INDICATOR_PANE_LABELS: Readonly<Record<string, string>> = {
  rsi: "RSI",
  macd: "MACD",
  stoch: "Stochastic",
  atr: "ATR",
  adx: "ADX",
  wr: "Williams %R",
  cci: "CCI",
  obv: "OBV",
  oi: "OI",
  stochrsi: "Stoch RSI",
  mfi: "MFI",
  squeeze: "Squeeze",
  ao: "Awesome Osc",
}

export const FLINT_CHART_INDICATOR_DEFAULT_PANE_SIZES: Readonly<FlintChartIndicatorPaneSizes> =
  Object.fromEntries(
    Object.keys(FLINT_CHART_INDICATOR_PANE_SPECS).map((scaleId) => [scaleId, "balanced"]),
  ) as FlintChartIndicatorPaneSizes

export const FLINT_CHART_INDICATOR_DEFAULT_PANE_STRETCH_FACTORS: Readonly<FlintChartIndicatorPaneStretchFactors> =
  Object.fromEntries(
    Object.keys(FLINT_CHART_INDICATOR_PANE_SPECS).map((scaleId) => [
      scaleId,
      FLINT_CHART_INDICATOR_PANE_STRETCH_FACTORS.balanced,
    ]),
  ) as FlintChartIndicatorPaneStretchFactors

const FLINT_CHART_INDICATOR_KEY_SET = new Set<FlintChartIndicatorKey>(
  FLINT_CHART_INDICATOR_DEFINITIONS.map((definition) => definition.key),
)
const FLINT_CHART_INDICATOR_PERIOD_KEY_SET = new Set<FlintChartIndicatorPeriodKey>(
  Object.keys(FLINT_CHART_DEFAULT_PERIODS) as FlintChartIndicatorPeriodKey[],
)
const FLINT_CHART_INDICATOR_COLOR_SET = new Set<string>(FLINT_CHART_INDICATOR_PALETTE)
const FLINT_CHART_INDICATOR_LINE_STYLE_SET = new Set<FlintChartIndicatorLineStyle>([
  "solid",
  "dashed",
  "dotted",
])
const FLINT_CHART_INDICATOR_PANE_SCALE_SET = new Set<string>(Object.keys(FLINT_CHART_INDICATOR_PANE_SPECS))
const FLINT_CHART_INDICATOR_PANE_SIZE_SET = new Set<FlintChartIndicatorPaneSize>(
  FLINT_CHART_INDICATOR_PANE_SIZE_OPTIONS,
)

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function parseJson(value: string | null): unknown {
  if (!value) return null
  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}

function normaliseIndicators(value: unknown): FlintChartIndicatorState {
  const next = { ...FLINT_CHART_DEFAULT_INDICATORS }
  if (!isRecord(value)) return next

  for (const [key, raw] of Object.entries(value)) {
    if (FLINT_CHART_INDICATOR_KEY_SET.has(key as FlintChartIndicatorKey) && typeof raw === "boolean") {
      next[key as FlintChartIndicatorKey] = raw
    }
  }

  return next
}

function normalisePeriods(value: unknown): FlintChartIndicatorPeriods {
  const next = { ...FLINT_CHART_DEFAULT_PERIODS }
  if (!isRecord(value)) return next

  for (const [key, raw] of Object.entries(value)) {
    if (
      FLINT_CHART_INDICATOR_PERIOD_KEY_SET.has(key as FlintChartIndicatorPeriodKey) &&
      typeof raw === "number" &&
      Number.isFinite(raw)
    ) {
      next[key as FlintChartIndicatorPeriodKey] = raw
    }
  }

  return next
}

function normaliseColors(value: unknown): Record<FlintChartIndicatorKey, FlintChartIndicatorColor> {
  const next = { ...FLINT_CHART_INDICATOR_DEFAULT_COLORS }
  if (!isRecord(value)) return next

  for (const [key, raw] of Object.entries(value)) {
    if (
      FLINT_CHART_INDICATOR_KEY_SET.has(key as FlintChartIndicatorKey) &&
      typeof raw === "string" &&
      FLINT_CHART_INDICATOR_COLOR_SET.has(raw)
    ) {
      next[key as FlintChartIndicatorKey] = raw as FlintChartIndicatorColor
    }
  }

  return next
}

function normaliseLineStyles(value: unknown): Record<FlintChartIndicatorKey, FlintChartIndicatorLineStyle> {
  const next = { ...FLINT_CHART_INDICATOR_DEFAULT_LINE_STYLES }
  if (!isRecord(value)) return next

  for (const [key, raw] of Object.entries(value)) {
    if (
      FLINT_CHART_INDICATOR_KEY_SET.has(key as FlintChartIndicatorKey) &&
      typeof raw === "string" &&
      FLINT_CHART_INDICATOR_LINE_STYLE_SET.has(raw as FlintChartIndicatorLineStyle)
    ) {
      next[key as FlintChartIndicatorKey] = raw as FlintChartIndicatorLineStyle
    }
  }

  return next
}

function normalisePaneSizes(value: unknown): FlintChartIndicatorPaneSizes {
  const next = { ...FLINT_CHART_INDICATOR_DEFAULT_PANE_SIZES }
  if (!isRecord(value)) return next

  for (const [scaleId, raw] of Object.entries(value)) {
    if (
      FLINT_CHART_INDICATOR_PANE_SCALE_SET.has(scaleId) &&
      typeof raw === "string" &&
      FLINT_CHART_INDICATOR_PANE_SIZE_SET.has(raw as FlintChartIndicatorPaneSize)
    ) {
      next[scaleId] = raw as FlintChartIndicatorPaneSize
    }
  }

  return next
}

function roundPaneStretchFactor(value: number): number {
  return Math.round(value * 100) / 100
}

function clampPaneStretchFactor(value: number): number {
  return Math.min(
    FLINT_CHART_INDICATOR_PANE_STRETCH_FACTOR_MAX,
    Math.max(FLINT_CHART_INDICATOR_PANE_STRETCH_FACTOR_MIN, value),
  )
}

function normalisePaneStretchFactors(
  value: unknown,
  paneSizes: FlintChartIndicatorPaneSizes = FLINT_CHART_INDICATOR_DEFAULT_PANE_SIZES,
): FlintChartIndicatorPaneStretchFactors {
  const next = Object.fromEntries(
    Object.keys(FLINT_CHART_INDICATOR_PANE_SPECS).map((scaleId) => [
      scaleId,
      getFlintChartIndicatorPaneStretchFactor(paneSizes[scaleId]),
    ]),
  ) as FlintChartIndicatorPaneStretchFactors
  if (!isRecord(value)) return next

  for (const [scaleId, raw] of Object.entries(value)) {
    if (
      FLINT_CHART_INDICATOR_PANE_SCALE_SET.has(scaleId) &&
      typeof raw === "number" &&
      Number.isFinite(raw) &&
      raw >= FLINT_CHART_INDICATOR_PANE_STRETCH_FACTOR_MIN &&
      raw <= FLINT_CHART_INDICATOR_PANE_STRETCH_FACTOR_MAX
    ) {
      next[scaleId] = roundPaneStretchFactor(raw)
    }
  }

  return next
}

function normaliseUpdatedAt(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0
}

export function createFlintChartDefaultIndicatorSettings(): FlintChartIndicatorSettings {
  return {
    version: FLINT_CHART_INDICATOR_SETTINGS_VERSION,
    indicators: { ...FLINT_CHART_DEFAULT_INDICATORS },
    periods: { ...FLINT_CHART_DEFAULT_PERIODS },
    colors: { ...FLINT_CHART_INDICATOR_DEFAULT_COLORS },
    lineStyles: { ...FLINT_CHART_INDICATOR_DEFAULT_LINE_STYLES },
    paneSizes: { ...FLINT_CHART_INDICATOR_DEFAULT_PANE_SIZES },
    paneStretchFactors: { ...FLINT_CHART_INDICATOR_DEFAULT_PANE_STRETCH_FACTORS },
    updatedAt: 0,
  }
}

export function parseFlintChartIndicatorSettings(
  value: string | null | unknown,
): FlintChartIndicatorSettings {
  const parsed = typeof value === "string" || value === null ? parseJson(value) : value
  if (!isRecord(parsed)) return createFlintChartDefaultIndicatorSettings()
  const paneSizes = normalisePaneSizes(parsed.paneSizes)

  return {
    version: FLINT_CHART_INDICATOR_SETTINGS_VERSION,
    indicators: normaliseIndicators(parsed.indicators),
    periods: normalisePeriods(parsed.periods),
    colors: normaliseColors(parsed.colors),
    lineStyles: normaliseLineStyles(parsed.lineStyles),
    paneSizes,
    paneStretchFactors: normalisePaneStretchFactors(parsed.paneStretchFactors, paneSizes),
    updatedAt: normaliseUpdatedAt(parsed.updatedAt),
  }
}

export function encodeFlintChartIndicatorSettings(
  settings: FlintChartIndicatorSettingsInput,
): string {
  const paneSizes = normalisePaneSizes(settings.paneSizes)
  return JSON.stringify({
    version: FLINT_CHART_INDICATOR_SETTINGS_VERSION,
    indicators: normaliseIndicators(settings.indicators),
    periods: normalisePeriods(settings.periods),
    colors: normaliseColors(settings.colors),
    lineStyles: normaliseLineStyles(settings.lineStyles),
    paneSizes,
    paneStretchFactors: normalisePaneStretchFactors(settings.paneStretchFactors, paneSizes),
    updatedAt: Date.now(),
  } satisfies FlintChartIndicatorSettings)
}

export function getFlintChartActiveIndicatorCount(
  indicators: FlintChartIndicatorState,
  options: { includeDefaultVolume?: boolean } = {},
): number {
  return FLINT_CHART_INDICATOR_DEFINITIONS.filter((definition) => {
    if (!options.includeDefaultVolume && definition.key === "showVolume") return false
    return indicators[definition.key]
  }).length
}

export function getFlintChartActiveIndicatorCountByCategory(
  indicators: FlintChartIndicatorState,
): Record<FlintChartIndicatorCategory, number> {
  return Object.fromEntries(
    FLINT_CHART_INDICATOR_CATEGORIES.map((category) => [
      category,
      FLINT_CHART_INDICATOR_DEFINITIONS.filter(
        (definition) => definition.category === category && indicators[definition.key],
      ).length,
    ]),
  ) as Record<FlintChartIndicatorCategory, number>
}

export function getFlintChartIndicatorPaneSpec(scaleId: string): FlintChartIndicatorPaneSpec | null {
  return FLINT_CHART_INDICATOR_PANE_SPECS[scaleId] ?? null
}

export function createFlintChartIndicatorPaneOptions(
  spec: FlintChartIndicatorPaneSpec,
): Record<string, unknown> {
  return {
    scaleMargins: spec.scaleMargins,
    ...(typeof spec.borderVisible === "boolean" ? { borderVisible: spec.borderVisible } : {}),
  }
}

export function createFlintChartIndicatorLineSeriesOptions(
  input: FlintChartIndicatorLineSeriesOptionsInput,
): FlintChartIndicatorLineSeriesOptions {
  const definition = input.key
    ? FLINT_CHART_INDICATOR_DEFINITIONS.find((candidate) => candidate.key === input.key)
    : undefined
  const rawLineStyle = input.lineStyle ?? "solid"
  const lineStyle = typeof rawLineStyle === "number"
    ? rawLineStyle
    : getFlintChartLineStyleCode(rawLineStyle)

  return {
    color: input.color ?? definition?.defaultColor ?? "#94a3b8",
    lineStyle,
    lineWidth: input.lineWidth ?? 1,
    priceScaleId: input.priceScaleId ?? definition?.priceScaleId ?? "right",
    title: input.title,
    lastValueVisible: input.lastValueVisible ?? false,
    priceLineVisible: input.priceLineVisible ?? false,
    ...(typeof input.pointMarkersVisible === "boolean"
      ? { pointMarkersVisible: input.pointMarkersVisible }
      : {}),
  }
}

export function createFlintChartIndicatorHistogramSeriesOptions(
  input: FlintChartIndicatorHistogramSeriesOptionsInput,
): FlintChartIndicatorHistogramSeriesOptions {
  return {
    priceScaleId: input.priceScaleId ?? "right",
    title: input.title,
    lastValueVisible: input.lastValueVisible ?? false,
    priceLineVisible: input.priceLineVisible ?? false,
  }
}

export function createFlintChartOIOverlaySeriesOptions(): FlintChartOIOverlaySeriesOptions {
  return {
    color: "rgba(99,102,241,0.5)",
    priceFormat: { type: "volume" },
    priceScaleId: "oi",
  }
}

export function createFlintChartOIProfileBarData<TTime>({
  latestTime,
  totalCeOi,
  totalPeOi,
}: FlintChartOIProfileBarDataInput<TTime>): FlintChartOIProfileBarData<TTime> | null {
  if (!Number.isFinite(totalCeOi) || !Number.isFinite(totalPeOi)) return null

  const absMax = Math.max(totalCeOi, totalPeOi)
  if (absMax <= 0) return null

  const net = totalCeOi - totalPeOi
  return {
    time: latestTime,
    value: Math.abs(net / absMax) * 100,
    color: net >= 0 ? "rgba(239,68,68,0.55)" : "rgba(34,197,94,0.55)",
  }
}

export function createFlintChartIndicatorSeriesRenderPlan({
  colors,
  indicators,
  lineStyles,
  paneSizes,
  paneStretchFactors,
  periods,
}: FlintChartIndicatorSeriesRenderPlanInput): FlintChartIndicatorSeriesRenderPlan {
  const normalisedIndicators = normaliseIndicators(indicators)
  const normalisedPeriods = normalisePeriods(periods)
  const normalisedColors = normaliseColors(colors)
  const normalisedLineStyles = normaliseLineStyles(lineStyles)
  const normalisedPaneSizes = normalisePaneSizes(paneSizes)
  const normalisedPaneStretchFactors = normalisePaneStretchFactors(paneStretchFactors, normalisedPaneSizes)
  const lifecyclePlan = createFlintChartIndicatorLifecyclePlan(normalisedIndicators)
  const paneLayoutPlan = createFlintChartIndicatorPaneLayoutPlan(
    normalisedIndicators,
    normalisedPaneSizes,
    normalisedPaneStretchFactors,
  )
  const lineSeries: FlintChartIndicatorLineSeriesRenderSpec[] = []
  const histogramSeries: FlintChartIndicatorHistogramSeriesRenderSpec[] = []

  const paneIndexForScale = (scaleId: string) => paneLayoutPlan.paneIndexByScaleId[scaleId]
  const addLineSeries = (
    indicatorKey: FlintChartIndicatorKey,
    refKey: FlintChartIndicatorSeriesRefKey,
    input: FlintChartIndicatorLineSeriesOptionsInput,
  ) => {
    const options = createFlintChartIndicatorLineSeriesOptions(input)
    lineSeries.push({
      key: `${indicatorKey}:line:${refKey}`,
      indicatorKey,
      refKey,
      paneScaleId: options.priceScaleId,
      paneIndex: paneIndexForScale(options.priceScaleId),
      options,
    })
  }
  const addHistogramSeries = (
    indicatorKey: FlintChartIndicatorKey,
    refKey: FlintChartIndicatorSeriesRefKey,
    input: FlintChartIndicatorHistogramSeriesOptionsInput,
  ) => {
    const options = createFlintChartIndicatorHistogramSeriesOptions(input)
    histogramSeries.push({
      key: `${indicatorKey}:histogram:${refKey}`,
      indicatorKey,
      refKey,
      paneScaleId: options.priceScaleId,
      paneIndex: paneIndexForScale(options.priceScaleId),
      options,
    })
  }
  const keyedLineOptions = (
    key: FlintChartIndicatorKey,
    title: string,
    overrides: Partial<FlintChartIndicatorLineSeriesOptionsInput> = {},
  ): FlintChartIndicatorLineSeriesOptionsInput => ({
    key,
    color: normalisedColors[key],
    lineStyle: normalisedLineStyles[key],
    title,
    ...overrides,
  })

  if (normalisedIndicators.showEMA20) {
    addLineSeries("showEMA20", "ema20", keyedLineOptions("showEMA20", `EMA${normalisedPeriods.ema1}`))
  }
  if (normalisedIndicators.showEMA50) {
    addLineSeries("showEMA50", "ema50", keyedLineOptions("showEMA50", `EMA${normalisedPeriods.ema2}`))
  }
  if (normalisedIndicators.showSMA) {
    addLineSeries("showSMA", "sma", keyedLineOptions("showSMA", `SMA${normalisedPeriods.sma}`))
  }
  if (normalisedIndicators.showWMA) {
    addLineSeries("showWMA", "wma", keyedLineOptions("showWMA", `WMA${normalisedPeriods.wma}`))
  }
  if (normalisedIndicators.showBB) {
    addLineSeries("showBB", "bbUpper", { color: "#ef4444", lineStyle: 2, priceScaleId: "right", title: "BB Upper" })
    addLineSeries("showBB", "bbMiddle", { color: "#94a3b8", lineStyle: 1, priceScaleId: "right", title: "BB Mid" })
    addLineSeries("showBB", "bbLower", { color: "#22c55e", lineStyle: 2, priceScaleId: "right", title: "BB Lower" })
  }
  if (normalisedIndicators.showSupertrend) {
    addLineSeries("showSupertrend", "stUp", { color: "#22c55e", lineWidth: 2, priceScaleId: "right", title: "ST Up" })
    addLineSeries("showSupertrend", "stDown", { color: "#ef4444", lineWidth: 2, priceScaleId: "right", title: "ST Down" })
  }
  if (normalisedIndicators.showVWAP) {
    addLineSeries("showVWAP", "vwap", keyedLineOptions("showVWAP", "VWAP", { lastValueVisible: true }))
  }
  if (normalisedIndicators.showIchimoku) {
    addLineSeries("showIchimoku", "ichTenkan", { color: "#ef4444", priceScaleId: "right", title: "Tenkan" })
    addLineSeries("showIchimoku", "ichKijun", { color: "#3b82f6", priceScaleId: "right", title: "Kijun" })
    addLineSeries("showIchimoku", "ichSenkouA", { color: "rgba(34,197,94,0.5)", priceScaleId: "right", title: "Senkou A" })
    addLineSeries("showIchimoku", "ichSenkouB", { color: "rgba(239,68,68,0.5)", priceScaleId: "right", title: "Senkou B" })
    addLineSeries("showIchimoku", "ichChikou", { color: "#a855f7", lineStyle: 2, priceScaleId: "right", title: "Chikou" })
  }
  if (normalisedIndicators.showRSI) {
    addLineSeries("showRSI", "rsi", keyedLineOptions("showRSI", `RSI(${normalisedPeriods.rsi})`, { lastValueVisible: true }))
  }
  if (normalisedIndicators.showMACD) {
    addHistogramSeries("showMACD", "macdHist", { priceScaleId: "macd", title: "MACD Hist" })
    addLineSeries("showMACD", "macdLine", { color: "#3b82f6", priceScaleId: "macd", title: "MACD" })
    addLineSeries("showMACD", "macdSignal", { color: "#f97316", priceScaleId: "macd", title: "Signal" })
  }
  if (normalisedIndicators.showStoch) {
    addLineSeries("showStoch", "stochK", { color: "#3b82f6", priceScaleId: "stoch", title: "%K" })
    addLineSeries("showStoch", "stochD", { color: "#f97316", priceScaleId: "stoch", title: "%D" })
  }
  if (normalisedIndicators.showATR) {
    addLineSeries("showATR", "atr", keyedLineOptions("showATR", `ATR(${normalisedPeriods.atr})`, { lastValueVisible: true }))
  }
  if (normalisedIndicators.showADX) {
    addLineSeries("showADX", "adx", { color: "#fbbf24", lastValueVisible: true, priceScaleId: "adx", title: "ADX" })
    addLineSeries("showADX", "adxPlus", { color: "#22c55e", priceScaleId: "adx", title: "+DI" })
    addLineSeries("showADX", "adxMinus", { color: "#ef4444", priceScaleId: "adx", title: "-DI" })
  }
  if (normalisedIndicators.showWilliamsR) {
    addLineSeries("showWilliamsR", "williamsR", keyedLineOptions("showWilliamsR", `W%R(${normalisedPeriods.wr})`, { lastValueVisible: true }))
  }
  if (normalisedIndicators.showCCI) {
    addLineSeries("showCCI", "cci", keyedLineOptions("showCCI", `CCI(${normalisedPeriods.cci})`, { lastValueVisible: true }))
  }
  if (normalisedIndicators.showDEMA) {
    addLineSeries("showDEMA", "dema", keyedLineOptions("showDEMA", `DEMA${normalisedPeriods.dema}`))
  }
  if (normalisedIndicators.showHullMA) {
    addLineSeries("showHullMA", "hullMA", keyedLineOptions("showHullMA", `HMA${normalisedPeriods.hull}`))
  }
  if (normalisedIndicators.showParabolicSAR) {
    addLineSeries("showParabolicSAR", "parSar", { color: "#facc15", pointMarkersVisible: true, priceScaleId: "right", title: "SAR" })
  }
  if (normalisedIndicators.showOBV) {
    addLineSeries("showOBV", "obv", keyedLineOptions("showOBV", "OBV", { lastValueVisible: true }))
  }
  if (normalisedIndicators.showKeltner) {
    addLineSeries("showKeltner", "keltnerUpper", { color: "rgba(249,115,22,0.4)", lineStyle: 2, priceScaleId: "right", title: "KC Upper" })
    addLineSeries("showKeltner", "keltnerMiddle", { color: "#f97316", priceScaleId: "right", title: "KC Mid" })
    addLineSeries("showKeltner", "keltnerLower", { color: "rgba(249,115,22,0.4)", lineStyle: 2, priceScaleId: "right", title: "KC Lower" })
  }
  if (normalisedIndicators.showVWMA) {
    addLineSeries("showVWMA", "vwma", keyedLineOptions("showVWMA", `VWMA${normalisedPeriods.vwma}`))
  }

  // --- Server-computed tier (series data arrives from the backend) ---
  if (normalisedIndicators.showKAMA) {
    addLineSeries("showKAMA", "kama", keyedLineOptions("showKAMA", `KAMA${normalisedPeriods.kama}`))
  }
  if (normalisedIndicators.showALMA) {
    addLineSeries("showALMA", "alma", keyedLineOptions("showALMA", `ALMA${normalisedPeriods.alma}`))
  }
  if (normalisedIndicators.showDonchian) {
    addLineSeries("showDonchian", "donUpper", { color: "rgba(56,189,248,0.5)", lineStyle: 2, priceScaleId: "right", title: "DC Upper" })
    addLineSeries("showDonchian", "donMiddle", { color: "#38bdf8", priceScaleId: "right", title: "DC Mid" })
    addLineSeries("showDonchian", "donLower", { color: "rgba(56,189,248,0.5)", lineStyle: 2, priceScaleId: "right", title: "DC Lower" })
  }
  if (normalisedIndicators.showChandelier) {
    addLineSeries("showChandelier", "chandLong", { color: "#22c55e", lineStyle: 2, priceScaleId: "right", title: "CE Long" })
    addLineSeries("showChandelier", "chandShort", { color: "#ef4444", lineStyle: 2, priceScaleId: "right", title: "CE Short" })
  }
  if (normalisedIndicators.showStochRSI) {
    addLineSeries("showStochRSI", "stochRsiK", keyedLineOptions("showStochRSI", `StochRSI %K(${normalisedPeriods.stochRsi})`, { lastValueVisible: true }))
    addLineSeries("showStochRSI", "stochRsiD", { color: "#f97316", priceScaleId: "stochrsi", title: "StochRSI %D" })
  }
  if (normalisedIndicators.showMFI) {
    addLineSeries("showMFI", "mfi", keyedLineOptions("showMFI", `MFI(${normalisedPeriods.mfi})`, { lastValueVisible: true }))
  }
  if (normalisedIndicators.showSqueeze) {
    addHistogramSeries("showSqueeze", "squeezeHist", { priceScaleId: "squeeze", title: "Squeeze" })
  }
  if (normalisedIndicators.showAO) {
    addHistogramSeries("showAO", "aoHist", { priceScaleId: "ao", title: "AO" })
  }

  return { lifecyclePlan, paneLayoutPlan, lineSeries, histogramSeries }
}

function areFlintChartIndicatorRenderSpecsEqual<TSpec>(previous: TSpec, next: TSpec): boolean {
  return JSON.stringify(previous) === JSON.stringify(next)
}

function createFlintChartIndicatorRenderPlanPartDiff<TSpec extends { key: string }>(
  previous: readonly TSpec[],
  next: readonly TSpec[],
): FlintChartIndicatorSeriesRenderPlanPartDiff<TSpec> {
  const previousByKey = new Map(previous.map((entry) => [entry.key, entry]))
  const nextByKey = new Map(next.map((entry) => [entry.key, entry]))
  const added: TSpec[] = []
  const updated: TSpec[] = []
  const unchanged: TSpec[] = []
  const removed: TSpec[] = []

  for (const nextSpec of next) {
    const previousSpec = previousByKey.get(nextSpec.key)
    if (!previousSpec) {
      added.push(nextSpec)
      continue
    }
    if (areFlintChartIndicatorRenderSpecsEqual(previousSpec, nextSpec)) {
      unchanged.push(nextSpec)
      continue
    }
    updated.push(nextSpec)
  }

  for (const previousSpec of previous) {
    if (!nextByKey.has(previousSpec.key)) {
      removed.push(previousSpec)
    }
  }

  return { added, updated, unchanged, removed }
}

export function createFlintChartIndicatorSeriesRenderPlanDiff(
  previous: FlintChartIndicatorSeriesRenderPlan,
  next: FlintChartIndicatorSeriesRenderPlan,
): FlintChartIndicatorSeriesRenderPlanDiff {
  return {
    lineSeries: createFlintChartIndicatorRenderPlanPartDiff(previous.lineSeries, next.lineSeries),
    histogramSeries: createFlintChartIndicatorRenderPlanPartDiff(previous.histogramSeries, next.histogramSeries),
  }
}

export function createFlintChartPivotPriceLineSpecs(
  pivots: PivotResult | null | undefined,
): FlintChartPriceLineSpec[] {
  if (!pivots) return []

  return [
    { price: pivots.pp, color: "#94a3b8", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "PP" },
    { price: pivots.r1, color: "#ef4444", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "R1" },
    { price: pivots.r2, color: "#f97316", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "R2" },
    { price: pivots.r3, color: "#dc2626", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "R3" },
    { price: pivots.s1, color: "#22c55e", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "S1" },
    { price: pivots.s2, color: "#16a34a", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "S2" },
    { price: pivots.s3, color: "#15803d", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "S3" },
  ]
}

export function createFlintChartIndicatorLifecyclePlan(
  indicators: FlintChartIndicatorState,
): FlintChartIndicatorLifecyclePlan {
  const normalised = normaliseIndicators(indicators)
  const activeDefinitions = FLINT_CHART_INDICATOR_DEFINITIONS.filter(
    (definition) => normalised[definition.key],
  )
  const activePriceScaleIds = Array.from(
    new Set(activeDefinitions.map((definition) => definition.priceScaleId)),
  )
  const paneSpecs = activePriceScaleIds
    .map((scaleId) => getFlintChartIndicatorPaneSpec(scaleId))
    .filter((spec): spec is FlintChartIndicatorPaneSpec => spec !== null)

  return {
    activeDefinitions,
    activeKeys: activeDefinitions.map((definition) => definition.key),
    activePriceScaleIds,
    paneSpecs,
    volumeVisible: normalised.showVolume,
  }
}

export function getFlintChartIndicatorPaneStretchFactor(
  size: FlintChartIndicatorPaneSize | undefined,
  customStretchFactor?: number,
): number {
  if (
    typeof customStretchFactor === "number" &&
    Number.isFinite(customStretchFactor) &&
    customStretchFactor >= FLINT_CHART_INDICATOR_PANE_STRETCH_FACTOR_MIN &&
    customStretchFactor <= FLINT_CHART_INDICATOR_PANE_STRETCH_FACTOR_MAX
  ) {
    return roundPaneStretchFactor(customStretchFactor)
  }
  return FLINT_CHART_INDICATOR_PANE_STRETCH_FACTORS[size ?? "balanced"]
}

export function createFlintChartIndicatorPaneLayoutPlan(
  indicators: FlintChartIndicatorState,
  paneSizes?: FlintChartIndicatorPaneSizes,
  paneStretchFactors?: FlintChartIndicatorPaneStretchFactors,
): FlintChartIndicatorPaneLayoutPlan {
  const lifecyclePlan = createFlintChartIndicatorLifecyclePlan(indicators)
  const normalisedPaneSizes = normalisePaneSizes(paneSizes)
  const normalisedPaneStretchFactors = normalisePaneStretchFactors(paneStretchFactors, normalisedPaneSizes)
  const panes = lifecyclePlan.paneSpecs.map((spec, index) => ({
    ...spec,
    paneIndex: index + 1,
    stretchFactor: getFlintChartIndicatorPaneStretchFactor(
      normalisedPaneSizes[spec.scaleId],
      normalisedPaneStretchFactors[spec.scaleId],
    ),
  }))
  const paneIndexByScaleId = Object.fromEntries(
    panes.map((pane) => [pane.scaleId, pane.paneIndex]),
  )

  return {
    mainPaneIndex: 0,
    mainPaneStretchFactor: panes.length > 0 ? 4 : 1,
    panes,
    paneIndexByScaleId,
  }
}

export function createFlintChartIndicatorPaneControls(
  indicators: FlintChartIndicatorState,
  paneSizes?: FlintChartIndicatorPaneSizes,
  paneStretchFactors?: FlintChartIndicatorPaneStretchFactors,
): FlintChartIndicatorPaneControl[] {
  const normalisedPaneSizes = normalisePaneSizes(paneSizes)
  const normalisedPaneStretchFactors = normalisePaneStretchFactors(paneStretchFactors, normalisedPaneSizes)
  return createFlintChartIndicatorPaneLayoutPlan(
    indicators,
    normalisedPaneSizes,
    normalisedPaneStretchFactors,
  ).panes.map((pane) => {
    const size = normalisedPaneSizes[pane.scaleId] ?? "balanced"
    const sizeStretchFactor = getFlintChartIndicatorPaneStretchFactor(size)
    return {
      scaleId: pane.scaleId,
      label: FLINT_CHART_INDICATOR_PANE_LABELS[pane.scaleId] ?? pane.scaleId.toUpperCase(),
      size,
      stretchFactor: pane.stretchFactor,
      isCustomSize: Math.abs(pane.stretchFactor - sizeStretchFactor) > 0.001,
    }
  })
}

export function resizeFlintChartIndicatorPaneStretchFactors(
  input: FlintChartIndicatorPaneResizeInput,
): FlintChartIndicatorPaneStretchFactors {
  const current = normalisePaneStretchFactors(input.paneStretchFactors)
  if (!FLINT_CHART_INDICATOR_PANE_SCALE_SET.has(input.scaleId)) return current

  const pixelsPerStretchFactor =
    typeof input.pixelsPerStretchFactor === "number" &&
    Number.isFinite(input.pixelsPerStretchFactor) &&
    input.pixelsPerStretchFactor > 0
      ? input.pixelsPerStretchFactor
      : FLINT_CHART_INDICATOR_PANE_RESIZE_PIXELS_PER_STRETCH_FACTOR
  const startStretchFactor = Number.isFinite(input.startStretchFactor)
    ? input.startStretchFactor
    : current[input.scaleId] ?? FLINT_CHART_INDICATOR_PANE_STRETCH_FACTORS.balanced
  const nextStretchFactor = roundPaneStretchFactor(
    clampPaneStretchFactor(startStretchFactor - input.deltaPixels / pixelsPerStretchFactor),
  )

  return {
    ...current,
    [input.scaleId]: nextStretchFactor,
  }
}

export function getFlintChartLineStyleCode(style: FlintChartIndicatorLineStyle): 0 | 1 | 2 {
  if (style === "dotted") return 1
  if (style === "dashed") return 2
  return 0
}
