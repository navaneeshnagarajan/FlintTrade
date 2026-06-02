/**
 * Compatibility exports for chart indicator calculations.
 *
 * The pure chart-rendering indicator math lives in `@flinttrade/design-system`
 * so chart behaviour is core-owned. Keep this local module as a stable import
 * shim while older chart code migrates.
 */

export {
  buildHistData,
  buildLineData,
  calcADX,
  calcATR,
  calcBollingerBands,
  calcCCI,
  calcDEMA,
  calcEMA,
  calcHullMA,
  calcIchimoku,
  calcKeltnerChannels,
  calcMACD,
  calcOBV,
  calcParabolicSAR,
  calcPivotPoints,
  calcRSI,
  calcSMA,
  calcStochastic,
  calcSupertrend,
  calcVWAP,
  calcVWMA,
  calcWMA,
  calcWilliamsR,
} from "@flinttrade/design-system";

export type {
  ADXResult,
  ATRResult,
  BBResult,
  FlintChartHistogramData,
  FlintChartLineData,
  FlintChartOhlcvBar,
  FlintChartTime,
  IchimokuResult,
  KeltnerResult,
  MACDResult,
  OhlcvBar,
  PivotResult,
  RSIResult,
  StochResult,
  SupertrendResult,
} from "@flinttrade/design-system";
