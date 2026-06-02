/**
 * indicators.ts
 *
 * Pure math functions for technical indicator calculations.
 * All functions are stateless and operate on plain number arrays.
 *
 * Used by: ChartWidget (overlays), OptionChain (derived signals),
 *          StraddlePnL (Greeks smoothing), AI signals package.
 *
 * No external dependencies — keeps the initial bundle small and makes
 * every function trivially testable without mocking.
 */

// ---------------------------------------------------------------------------
// Simple Moving Average (SMA)
// ---------------------------------------------------------------------------

/**
 * Compute the Simple Moving Average of a price series.
 *
 * Returns an array whose length equals `prices.length - period + 1`.
 * Each element is the arithmetic mean of the preceding `period` values.
 *
 * Returns an empty array when:
 *   - `prices` is empty, or
 *   - `period` is larger than `prices.length`.
 */
export function sma(prices: number[], period: number): number[] {
  if (prices.length === 0 || period <= 0 || period > prices.length) return [];
  const result: number[] = [];
  for (let i = period - 1; i < prices.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) {
      sum += prices[j];
    }
    result.push(sum / period);
  }
  return result;
}

// ---------------------------------------------------------------------------
// Exponential Moving Average (EMA)
// ---------------------------------------------------------------------------

/**
 * Compute the Exponential Moving Average of a price series.
 *
 * Uses the standard smoothing factor k = 2 / (period + 1).
 * The first EMA value is seeded with the SMA of the first `period` prices.
 *
 * Returns an array of length `prices.length - period + 1`.
 * Returns an empty array when `prices` is empty or `period > prices.length`.
 */
export function ema(prices: number[], period: number): number[] {
  if (prices.length === 0 || period <= 0 || period > prices.length) return [];
  const k = 2 / (period + 1);

  // Seed with SMA of the first `period` values
  let prev = prices.slice(0, period).reduce((a, b) => a + b, 0) / period;
  const result: number[] = [prev];

  for (let i = period; i < prices.length; i++) {
    prev = prices[i] * k + prev * (1 - k);
    result.push(prev);
  }
  return result;
}

// ---------------------------------------------------------------------------
// Relative Strength Index (RSI)
// ---------------------------------------------------------------------------

/**
 * Compute the RSI using Wilder's smoothing method.
 *
 * Returns an array of length `prices.length - period`.
 * Returns an empty array when `prices` is too short.
 * Values are in the range [0, 100].
 */
export function rsi(prices: number[], period: number = 14): number[] {
  if (prices.length <= period || period <= 0) return [];

  const gains: number[] = [];
  const losses: number[] = [];

  for (let i = 1; i < prices.length; i++) {
    const delta = prices[i] - prices[i - 1];
    gains.push(delta > 0 ? delta : 0);
    losses.push(delta < 0 ? -delta : 0);
  }

  // Initial average gain/loss over first `period` bars
  let avgGain = gains.slice(0, period).reduce((a, b) => a + b, 0) / period;
  let avgLoss = losses.slice(0, period).reduce((a, b) => a + b, 0) / period;

  const result: number[] = [];

  const toRsi = (ag: number, al: number): number => {
    if (al === 0) return 100;
    const rs = ag / al;
    return 100 - 100 / (1 + rs);
  };

  result.push(toRsi(avgGain, avgLoss));

  // Wilder's smoothing for subsequent bars
  for (let i = period; i < gains.length; i++) {
    avgGain = (avgGain * (period - 1) + gains[i]) / period;
    avgLoss = (avgLoss * (period - 1) + losses[i]) / period;
    result.push(toRsi(avgGain, avgLoss));
  }

  return result;
}

// ---------------------------------------------------------------------------
// Bollinger Bands
// ---------------------------------------------------------------------------

export interface BollingerBand {
  upper: number;
  middle: number;
  lower: number;
}

/**
 * Compute Bollinger Bands (upper, middle, lower) for each SMA window.
 *
 * `stdDevMultiplier` defaults to 2.0 (standard practice).
 * Returns an array of the same length as `sma(prices, period)`.
 */
export function bollingerBands(
  prices: number[],
  period: number,
  stdDevMultiplier: number = 2,
): BollingerBand[] {
  if (prices.length === 0 || period <= 0 || period > prices.length) return [];

  const result: BollingerBand[] = [];

  for (let i = period - 1; i < prices.length; i++) {
    const window = prices.slice(i - period + 1, i + 1);
    const mean = window.reduce((a, b) => a + b, 0) / period;
    const variance = window.reduce((a, b) => a + (b - mean) ** 2, 0) / period;
    const stdDev = Math.sqrt(variance);

    result.push({
      upper: mean + stdDevMultiplier * stdDev,
      middle: mean,
      lower: mean - stdDevMultiplier * stdDev,
    });
  }

  return result;
}

// ---------------------------------------------------------------------------
// MACD
// ---------------------------------------------------------------------------

/**
 * API response shape for MACD from the FlintTrade indicators compute endpoint
 * (POST /ft-api/v1/indicators/macd). Uses `histogram` (not `hist`) and
 * returns non-nullable number arrays because nulls are stripped server-side.
 *
 * Distinct from design-system `MACDResult` for chart rendering, which uses
 * `hist` and nullable arrays.
 */
export interface MACDApiResult {
  macd: number[];
  signal: number[];
  histogram: number[];
}

/**
 * Compute MACD (fast EMA - slow EMA), Signal line (EMA of MACD),
 * and Histogram (MACD - Signal).
 *
 * Standard parameters: fast=12, slow=26, signal=9.
 */
export function macd(
  prices: number[],
  fastPeriod: number = 12,
  slowPeriod: number = 26,
  signalPeriod: number = 9,
): MACDApiResult {
  const emptyResult: MACDApiResult = { macd: [], signal: [], histogram: [] };

  if (prices.length < slowPeriod + signalPeriod - 1) return emptyResult;

  const fastEma = ema(prices, fastPeriod);
  const slowEma = ema(prices, slowPeriod);

  // Align: slowEma is shorter; trim fastEma to match
  const offset = slowPeriod - fastPeriod;
  const alignedFast = fastEma.slice(offset);

  const macdLine = alignedFast.map((f, i) => f - slowEma[i]);

  if (macdLine.length < signalPeriod) return emptyResult;

  const signalLine = ema(macdLine, signalPeriod);

  // Align macdLine with signal (signal starts at index signalPeriod - 1)
  const alignedMacd = macdLine.slice(signalPeriod - 1);
  const histogram = alignedMacd.map((m, i) => m - signalLine[i]);

  return { macd: alignedMacd, signal: signalLine, histogram };
}

// ---------------------------------------------------------------------------
// Average True Range (ATR)
// ---------------------------------------------------------------------------

/**
 * Compute the Average True Range using Wilder's smoothing.
 *
 * Requires both `highs`, `lows`, and `closes` arrays of equal length.
 * Returns an array of length `closes.length - period`.
 */
export function atr(
  highs: number[],
  lows: number[],
  closes: number[],
  period: number = 14,
): number[] {
  const len = closes.length;
  if (len !== highs.length || len !== lows.length) return [];
  if (len <= period || period <= 0) return [];

  // Compute True Range for each bar (starting from index 1)
  const tr: number[] = [];
  for (let i = 1; i < len; i++) {
    const highLow = highs[i] - lows[i];
    const highPrevClose = Math.abs(highs[i] - closes[i - 1]);
    const lowPrevClose = Math.abs(lows[i] - closes[i - 1]);
    tr.push(Math.max(highLow, highPrevClose, lowPrevClose));
  }

  // Seed with simple average of first `period` TR values
  let atrVal = tr.slice(0, period).reduce((a, b) => a + b, 0) / period;
  const result: number[] = [atrVal];

  // Wilder's smoothing
  for (let i = period; i < tr.length; i++) {
    atrVal = (atrVal * (period - 1) + tr[i]) / period;
    result.push(atrVal);
  }

  return result;
}

// ---------------------------------------------------------------------------
// Standard Deviation (rolling)
// ---------------------------------------------------------------------------

/**
 * Compute the rolling population standard deviation over `period` bars.
 * Returns an array of length `prices.length - period + 1`.
 */
export function rollingStdDev(prices: number[], period: number): number[] {
  if (prices.length === 0 || period <= 0 || period > prices.length) return [];
  const result: number[] = [];

  for (let i = period - 1; i < prices.length; i++) {
    const window = prices.slice(i - period + 1, i + 1);
    const mean = window.reduce((a, b) => a + b, 0) / period;
    const variance = window.reduce((a, b) => a + (b - mean) ** 2, 0) / period;
    result.push(Math.sqrt(variance));
  }

  return result;
}

// ---------------------------------------------------------------------------
// Rate of Change (ROC)
// ---------------------------------------------------------------------------

/**
 * Compute the Rate of Change as a percentage:
 *   ROC = (price[i] - price[i - period]) / price[i - period] * 100
 *
 * Returns an array of length `prices.length - period`.
 */
export function roc(prices: number[], period: number): number[] {
  if (prices.length <= period || period <= 0) return [];
  const result: number[] = [];
  for (let i = period; i < prices.length; i++) {
    const prev = prices[i - period];
    if (prev === 0) {
      result.push(0);
    } else {
      result.push(((prices[i] - prev) / prev) * 100);
    }
  }
  return result;
}

// ---------------------------------------------------------------------------
// Highest High / Lowest Low (rolling)
// ---------------------------------------------------------------------------

/**
 * Rolling highest value over `period` bars.
 * Returns array of length `prices.length - period + 1`.
 */
export function rollingMax(prices: number[], period: number): number[] {
  if (prices.length === 0 || period <= 0 || period > prices.length) return [];
  const result: number[] = [];
  for (let i = period - 1; i < prices.length; i++) {
    result.push(Math.max(...prices.slice(i - period + 1, i + 1)));
  }
  return result;
}

/**
 * Rolling lowest value over `period` bars.
 * Returns array of length `prices.length - period + 1`.
 */
export function rollingMin(prices: number[], period: number): number[] {
  if (prices.length === 0 || period <= 0 || period > prices.length) return [];
  const result: number[] = [];
  for (let i = period - 1; i < prices.length; i++) {
    result.push(Math.min(...prices.slice(i - period + 1, i + 1)));
  }
  return result;
}

// ---------------------------------------------------------------------------
// Stochastic Oscillator (%K)
// ---------------------------------------------------------------------------

/**
 * Compute raw Stochastic %K:
 *   %K = (close - lowest_low) / (highest_high - lowest_low) * 100
 *
 * Returns array of length `closes.length - period + 1`.
 * Returns 50 when highest_high === lowest_low (flat candle).
 */
export function stochasticK(
  highs: number[],
  lows: number[],
  closes: number[],
  period: number = 14,
): number[] {
  const len = closes.length;
  if (len !== highs.length || len !== lows.length) return [];
  if (len < period || period <= 0) return [];

  const result: number[] = [];
  for (let i = period - 1; i < len; i++) {
    const windowHighs = highs.slice(i - period + 1, i + 1);
    const windowLows = lows.slice(i - period + 1, i + 1);
    const hh = Math.max(...windowHighs);
    const ll = Math.min(...windowLows);
    const range = hh - ll;
    result.push(range === 0 ? 50 : ((closes[i] - ll) / range) * 100);
  }
  return result;
}

// ---------------------------------------------------------------------------
// Cumulative Sum
// ---------------------------------------------------------------------------

/**
 * Compute the cumulative sum of an array.
 * Returns an array of the same length as the input.
 */
export function cumsum(values: number[]): number[] {
  let running = 0;
  return values.map((v) => {
    running += v;
    return running;
  });
}

// ---------------------------------------------------------------------------
// NaN-safe helpers
// ---------------------------------------------------------------------------

/**
 * Filter NaN values from a prices array before passing to indicator functions.
 * Returns the filtered array so callers can check length themselves.
 */
export function filterNaN(prices: number[]): number[] {
  return prices.filter((v) => !Number.isNaN(v));
}

/**
 * Returns true if every element in the array is a finite number.
 */
export function allFinite(values: number[]): boolean {
  return values.every((v) => Number.isFinite(v));
}
