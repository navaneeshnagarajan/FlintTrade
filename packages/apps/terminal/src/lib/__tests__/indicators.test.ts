/**
 * indicators.test.ts
 *
 * Tests for all exported functions in lib/indicators.ts.
 *
 * Verification strategy:
 *   - All expected SMA/EMA values are computed by hand or cross-checked
 *     against known references so the test inputs are self-documenting.
 *   - Edge cases (empty, single element, NaN, period > length) are grouped
 *     at the top of each describe block under "edge cases".
 *   - Floating-point comparisons use toBeCloseTo(value, decimalPlaces)
 *     where the exact output depends on rounding.
 */

import { describe, it, expect } from "vitest";
import {
  sma,
  ema,
  rsi,
  bollingerBands,
  macd,
  atr,
  rollingStdDev,
  roc,
  rollingMax,
  rollingMin,
  stochasticK,
  cumsum,
  filterNaN,
  allFinite,
} from "../indicators";

// ---------------------------------------------------------------------------
// SMA — Simple Moving Average
// ---------------------------------------------------------------------------

describe("sma", () => {
  // --- happy path ---

  it("computes period-3 SMA for [1,2,3,4,5]", () => {
    // Arrange
    const prices = [1, 2, 3, 4, 5];
    // Act
    const result = sma(prices, 3);
    // Assert — windows: [1,2,3]=2, [2,3,4]=3, [3,4,5]=4
    expect(result).toEqual([2, 3, 4]);
  });

  it("computes period-1 SMA (identity — returns every price)", () => {
    const prices = [10, 20, 30];
    expect(sma(prices, 1)).toEqual([10, 20, 30]);
  });

  it("computes period-equal-to-length SMA (single value — the mean)", () => {
    const prices = [2, 4, 6, 8];
    // Mean of all four = 5
    expect(sma(prices, 4)).toEqual([5]);
  });

  it("returns length prices.length - period + 1", () => {
    const prices = Array.from({ length: 10 }, (_, i) => i + 1);
    const result = sma(prices, 3);
    expect(result).toHaveLength(10 - 3 + 1); // 8
  });

  it("computes period-5 SMA for a longer series", () => {
    const prices = [10, 20, 30, 40, 50, 60, 70];
    // Windows: [10..50]=30, [20..60]=40, [30..70]=50
    expect(sma(prices, 5)).toEqual([30, 40, 50]);
  });

  it("handles all-identical prices (SMA equals that price)", () => {
    const prices = [7, 7, 7, 7, 7];
    expect(sma(prices, 3)).toEqual([7, 7, 7]);
  });

  it("handles negative prices correctly", () => {
    const prices = [-3, -1, 1, 3];
    // Windows: [-3,-1,1]=(-3)/3= -1, [-1,1,3]=3/3=1
    expect(sma(prices, 3)).toEqual([-1, 1]);
  });

  // --- edge cases ---

  it("returns [] for an empty array", () => {
    expect(sma([], 3)).toEqual([]);
  });

  it("returns [] when period is 0", () => {
    expect(sma([1, 2, 3], 0)).toEqual([]);
  });

  it("returns [] when period is negative", () => {
    expect(sma([1, 2, 3], -1)).toEqual([]);
  });

  it("returns [] when period exceeds length", () => {
    expect(sma([1, 2], 5)).toEqual([]);
  });

  it("returns [] for a single-element array with period 2", () => {
    expect(sma([42], 2)).toEqual([]);
  });

  it("handles a single-element array with period 1", () => {
    expect(sma([42], 1)).toEqual([42]);
  });
});

// ---------------------------------------------------------------------------
// EMA — Exponential Moving Average
// ---------------------------------------------------------------------------

describe("ema", () => {
  // --- happy path ---

  it("seeds the first value with the SMA of the first period", () => {
    // Arrange: prices=[10,20,30], period=3
    // Seed = SMA([10,20,30]) = 20; no subsequent values → result = [20]
    const result = ema([10, 20, 30], 3);
    expect(result).toHaveLength(1);
    expect(result[0]).toBe(20);
  });

  it("applies the EMA recurrence correctly", () => {
    // Arrange: prices=[10,20,30,40], period=3
    // k = 2/(3+1) = 0.5
    // EMA[0] = seed = SMA([10,20,30]) = 20
    // EMA[1] = 40 * 0.5 + 20 * 0.5 = 30
    const result = ema([10, 20, 30, 40], 3);
    expect(result).toHaveLength(2);
    expect(result[0]).toBeCloseTo(20, 6);
    expect(result[1]).toBeCloseTo(30, 6);
  });

  it("produces a length of prices.length - period + 1", () => {
    const prices = Array.from({ length: 10 }, (_, i) => i + 1);
    const result = ema(prices, 3);
    expect(result).toHaveLength(10 - 3 + 1);
  });

  it("EMA follows price trend upward", () => {
    const prices = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
    const result = ema(prices, 3);
    // Each value should be greater than the previous as prices rise
    for (let i = 1; i < result.length; i++) {
      expect(result[i]).toBeGreaterThan(result[i - 1]);
    }
  });

  it("EMA converges to a constant when prices are flat", () => {
    const prices = [10, 10, 10, 10, 10, 10, 10];
    const result = ema(prices, 3);
    result.forEach((v) => expect(v).toBeCloseTo(10, 6));
  });

  it("period-1 EMA equals the input prices (k=1, no smoothing)", () => {
    // k = 2/(1+1) = 1 → EMA[i] = price[i]
    const prices = [5, 10, 15, 20];
    const result = ema(prices, 1);
    expect(result).toEqual([5, 10, 15, 20]);
  });

  it("handles period equal to prices.length (single output)", () => {
    const prices = [2, 4, 6, 8];
    const result = ema(prices, 4);
    expect(result).toHaveLength(1);
    expect(result[0]).toBeCloseTo(5, 6); // SMA seed = mean = 5
  });

  // --- edge cases ---

  it("returns [] for an empty array", () => {
    expect(ema([], 3)).toEqual([]);
  });

  it("returns [] when period is 0", () => {
    expect(ema([1, 2, 3], 0)).toEqual([]);
  });

  it("returns [] when period is negative", () => {
    expect(ema([1, 2, 3], -5)).toEqual([]);
  });

  it("returns [] when period exceeds length", () => {
    expect(ema([1, 2], 5)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// RSI — Relative Strength Index
// ---------------------------------------------------------------------------

describe("rsi", () => {
  // --- happy path ---

  it("returns 100 when all moves are gains", () => {
    // Strictly increasing prices → all gains, no losses → RSI = 100
    const prices = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24];
    const result = rsi(prices, 14);
    expect(result[0]).toBe(100);
  });

  it("returns 0 when all moves are losses", () => {
    // Strictly decreasing → all losses, no gains → RSI = 0
    const prices = [20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6];
    const result = rsi(prices, 14);
    expect(result[0]).toBe(0);
  });

  it("returns 50 for perfectly alternating equal gains and losses", () => {
    // +1, -1, +1, -1 … → avgGain === avgLoss → RS = 1 → RSI = 50
    const prices: number[] = [100];
    for (let i = 0; i < 20; i++) {
      prices.push(prices[prices.length - 1] + (i % 2 === 0 ? 1 : -1));
    }
    const result = rsi(prices, 14);
    // Not exactly 50 due to Wilder smoothing seed, but close
    expect(result[0]).toBeCloseTo(50, 0);
  });

  it("returns values within [0, 100]", () => {
    const prices = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.15,
      43.61, 44.33, 44.83, 45.10, 45.15, 43.61, 44.33, 44.83];
    const result = rsi(prices, 14);
    result.forEach((v) => {
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(100);
    });
  });

  it("produces length prices.length - period values", () => {
    const prices = Array.from({ length: 20 }, (_, i) => 100 + i);
    const result = rsi(prices, 14);
    expect(result).toHaveLength(20 - 14);
  });

  // --- edge cases ---

  it("returns [] when prices.length === period (need at least period+1)", () => {
    const prices = Array.from({ length: 14 }, (_, i) => i + 1);
    expect(rsi(prices, 14)).toEqual([]);
  });

  it("returns [] for an empty array", () => {
    expect(rsi([], 14)).toEqual([]);
  });

  it("returns [] when period is 0", () => {
    expect(rsi([1, 2, 3], 0)).toEqual([]);
  });

  it("returns [] when prices are shorter than period", () => {
    expect(rsi([1, 2, 3], 14)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// Bollinger Bands
// ---------------------------------------------------------------------------

describe("bollingerBands", () => {
  // --- happy path ---

  it("upper > middle > lower for a non-constant series", () => {
    const prices = [10, 12, 14, 13, 15, 11, 16, 12];
    const result = bollingerBands(prices, 5);
    result.forEach(({ upper, middle, lower }) => {
      expect(upper).toBeGreaterThan(middle);
      expect(middle).toBeGreaterThan(lower);
    });
  });

  it("middle equals SMA of the window", () => {
    const prices = [1, 2, 3, 4, 5, 6, 7];
    const bands = bollingerBands(prices, 3);
    const smaSeries = sma(prices, 3);
    bands.forEach((band, i) => {
      expect(band.middle).toBeCloseTo(smaSeries[i], 10);
    });
  });

  it("upper === lower === middle when prices are constant (zero std dev)", () => {
    const prices = [5, 5, 5, 5, 5];
    const result = bollingerBands(prices, 3);
    result.forEach(({ upper, middle, lower }) => {
      expect(upper).toBe(middle);
      expect(lower).toBe(middle);
    });
  });

  it("respects the stdDevMultiplier parameter", () => {
    const prices = [10, 20, 30, 40, 50];
    const bands1 = bollingerBands(prices, 3, 1);
    const bands2 = bollingerBands(prices, 3, 2);
    // With multiplier 2, bands should be twice as wide as multiplier 1
    bands1.forEach((_b1, i) => {
      const width1 = bands1[i].upper - bands1[i].middle;
      const width2 = bands2[i].upper - bands2[i].middle;
      expect(width2).toBeCloseTo(width1 * 2, 10);
    });
  });

  it("returns length prices.length - period + 1", () => {
    const prices = Array.from({ length: 10 }, (_, i) => i);
    expect(bollingerBands(prices, 4)).toHaveLength(7);
  });

  // --- edge cases ---

  it("returns [] for an empty array", () => {
    expect(bollingerBands([], 3)).toEqual([]);
  });

  it("returns [] when period exceeds length", () => {
    expect(bollingerBands([1, 2], 5)).toEqual([]);
  });

  it("returns [] when period is 0", () => {
    expect(bollingerBands([1, 2, 3], 0)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// MACD
// ---------------------------------------------------------------------------

describe("macd", () => {
  // --- happy path ---

  it("returns three arrays: macd, signal, histogram", () => {
    // Generate 50 prices (enough for default params 12/26/9)
    const prices = Array.from({ length: 50 }, (_, i) => 100 + Math.sin(i) * 5);
    const result = macd(prices, 12, 26, 9);
    expect(Array.isArray(result.macd)).toBe(true);
    expect(Array.isArray(result.signal)).toBe(true);
    expect(Array.isArray(result.histogram)).toBe(true);
  });

  it("histogram equals macd minus signal element-wise", () => {
    const prices = Array.from({ length: 50 }, (_, i) => 100 + i * 0.5);
    const result = macd(prices, 12, 26, 9);
    result.histogram.forEach((h, i) => {
      expect(h).toBeCloseTo(result.macd[i] - result.signal[i], 10);
    });
  });

  it("macd, signal, and histogram arrays have equal length", () => {
    const prices = Array.from({ length: 60 }, (_, i) => 100 + i);
    const result = macd(prices, 12, 26, 9);
    expect(result.macd.length).toBe(result.signal.length);
    expect(result.signal.length).toBe(result.histogram.length);
  });

  it("MACD is positive when fast EMA > slow EMA (uptrend)", () => {
    // Strong uptrend → fast EMA (12) > slow EMA (26) → MACD > 0
    const prices = Array.from({ length: 50 }, (_, i) => i * 2);
    const result = macd(prices, 12, 26, 9);
    // Check last few values of an uptrend series
    const last = result.macd[result.macd.length - 1];
    expect(last).toBeGreaterThan(0);
  });

  // --- edge cases ---

  it("returns empty arrays when prices are too short", () => {
    const prices = Array.from({ length: 30 }, (_, i) => i);
    const result = macd(prices, 12, 26, 9); // needs ≥ 34 prices
    expect(result.macd).toEqual([]);
    expect(result.signal).toEqual([]);
    expect(result.histogram).toEqual([]);
  });

  it("returns empty arrays for an empty input", () => {
    const result = macd([]);
    expect(result.macd).toEqual([]);
    expect(result.signal).toEqual([]);
    expect(result.histogram).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// ATR — Average True Range
// ---------------------------------------------------------------------------

describe("atr", () => {
  // Generates deterministic OHLC data: high = base+1, low = base-1, close = base
  function makeOHLC(closes: number[]) {
    return {
      highs: closes.map((c) => c + 1),
      lows: closes.map((c) => c - 1),
      closes,
    };
  }

  it("produces non-negative ATR values", () => {
    const closes = Array.from({ length: 20 }, (_, i) => 100 + i);
    const { highs, lows } = makeOHLC(closes);
    const result = atr(highs, lows, closes, 14);
    result.forEach((v) => expect(v).toBeGreaterThanOrEqual(0));
  });

  it("returns length closes.length - period", () => {
    const closes = Array.from({ length: 20 }, (_, i) => 100 + i);
    const { highs, lows } = makeOHLC(closes);
    const result = atr(highs, lows, closes, 14);
    expect(result).toHaveLength(20 - 14);
  });

  it("ATR is constant for flat OHLC with equal high-low spread", () => {
    // Every bar: high=101, low=99, close=100 → TR = max(2, 1, 1) = 2
    const closes = new Array(20).fill(100) as number[];
    const highs = new Array(20).fill(101) as number[];
    const lows = new Array(20).fill(99) as number[];
    const result = atr(highs, lows, closes, 14);
    result.forEach((v) => expect(v).toBeCloseTo(2, 6));
  });

  // --- edge cases ---

  it("returns [] when highs/lows/closes have mismatched lengths", () => {
    expect(atr([10, 11], [9, 10], [10], 1)).toEqual([]);
  });

  it("returns [] when prices.length <= period", () => {
    const closes = new Array(14).fill(100) as number[];
    const highs = new Array(14).fill(101) as number[];
    const lows = new Array(14).fill(99) as number[];
    expect(atr(highs, lows, closes, 14)).toEqual([]);
  });

  it("returns [] for empty arrays", () => {
    expect(atr([], [], [], 14)).toEqual([]);
  });

  it("returns [] when period is 0", () => {
    const closes = [100, 101, 102, 103];
    const highs = [101, 102, 103, 104];
    const lows = [99, 100, 101, 102];
    expect(atr(highs, lows, closes, 0)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// rollingStdDev
// ---------------------------------------------------------------------------

describe("rollingStdDev", () => {
  it("returns 0 for a constant series", () => {
    const prices = [5, 5, 5, 5, 5];
    const result = rollingStdDev(prices, 3);
    result.forEach((v) => expect(v).toBeCloseTo(0, 10));
  });

  it("computes correct population std dev for a known series", () => {
    // Window [1,2,3]: mean=2, variance=(1+0+1)/3=2/3, stdDev≈0.8165
    const result = rollingStdDev([1, 2, 3, 4, 5], 3);
    expect(result[0]).toBeCloseTo(Math.sqrt(2 / 3), 6);
    // Window [2,3,4]: same spread → same std dev
    expect(result[1]).toBeCloseTo(Math.sqrt(2 / 3), 6);
  });

  it("returns length prices.length - period + 1", () => {
    expect(rollingStdDev([1, 2, 3, 4, 5, 6], 3)).toHaveLength(4);
  });

  it("returns [] for empty input", () => {
    expect(rollingStdDev([], 3)).toEqual([]);
  });

  it("returns [] when period exceeds length", () => {
    expect(rollingStdDev([1, 2], 5)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// ROC — Rate of Change
// ---------------------------------------------------------------------------

describe("roc", () => {
  it("computes correct ROC for a simple series", () => {
    // prices=[100,110], period=1 → ROC = (110-100)/100*100 = 10%
    expect(roc([100, 110], 1)).toEqual([10]);
  });

  it("computes ROC for period > 1", () => {
    // prices=[100,105,110], period=2 → ROC = (110-100)/100*100 = 10%
    const result = roc([100, 105, 110], 2);
    expect(result).toHaveLength(1);
    expect(result[0]).toBeCloseTo(10, 6);
  });

  it("returns negative ROC for a falling price", () => {
    expect(roc([100, 90], 1)[0]).toBeCloseTo(-10, 6);
  });

  it("returns 0 when the base price is 0 (division guard)", () => {
    expect(roc([0, 10], 1)).toEqual([0]);
  });

  it("returns length prices.length - period", () => {
    const prices = Array.from({ length: 8 }, (_, i) => 100 + i);
    expect(roc(prices, 3)).toHaveLength(5);
  });

  it("returns [] for empty input", () => {
    expect(roc([], 3)).toEqual([]);
  });

  it("returns [] when period equals length", () => {
    expect(roc([1, 2, 3], 3)).toEqual([]);
  });

  it("returns [] when period is 0", () => {
    expect(roc([1, 2, 3], 0)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// rollingMax / rollingMin
// ---------------------------------------------------------------------------

describe("rollingMax", () => {
  it("returns period-window maximum", () => {
    // period=3: [1,3,2]=3, [3,2,4]=4, [2,4,1]=4
    expect(rollingMax([1, 3, 2, 4, 1], 3)).toEqual([3, 4, 4]);
  });

  it("equals the only element for period == length", () => {
    expect(rollingMax([5, 2, 8, 1], 4)).toEqual([8]);
  });

  it("returns the input for period 1", () => {
    expect(rollingMax([3, 1, 4, 1, 5], 1)).toEqual([3, 1, 4, 1, 5]);
  });

  it("returns [] for empty input", () => {
    expect(rollingMax([], 3)).toEqual([]);
  });

  it("returns [] when period exceeds length", () => {
    expect(rollingMax([1, 2], 5)).toEqual([]);
  });
});

describe("rollingMin", () => {
  it("returns period-window minimum", () => {
    // period=3: [1,3,2]=1, [3,2,4]=2, [2,4,1]=1
    expect(rollingMin([1, 3, 2, 4, 1], 3)).toEqual([1, 2, 1]);
  });

  it("equals the only element for period == length", () => {
    expect(rollingMin([5, 2, 8, 1], 4)).toEqual([1]);
  });

  it("returns the input for period 1", () => {
    expect(rollingMin([3, 1, 4, 1, 5], 1)).toEqual([3, 1, 4, 1, 5]);
  });

  it("returns [] for empty input", () => {
    expect(rollingMin([], 3)).toEqual([]);
  });

  it("returns [] when period exceeds length", () => {
    expect(rollingMin([1, 2], 5)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// Stochastic %K
// ---------------------------------------------------------------------------

describe("stochasticK", () => {
  it("returns 100 when close equals highest high", () => {
    const highs = [10, 12, 15, 14, 15];
    const lows = [8, 9, 10, 10, 10];
    const closes = [10, 12, 15, 14, 15]; // close = high on last bar
    const result = stochasticK(highs, lows, closes, 5);
    expect(result).toHaveLength(1);
    // close=15 = hh=15, ll=8 → (15-8)/(15-8)*100 = 100
    expect(result[0]).toBeCloseTo(100, 6);
  });

  it("returns 0 when close equals lowest low", () => {
    const highs = [15, 14, 15, 12, 10];
    const lows = [10, 10, 10, 9, 8];
    const closes = [15, 14, 15, 12, 8]; // close = low on last bar
    const result = stochasticK(highs, lows, closes, 5);
    // close=8 = ll=8 → (8-8)/(15-8)*100 = 0
    expect(result[0]).toBeCloseTo(0, 6);
  });

  it("returns 50 when the range is zero (flat candles)", () => {
    const highs = [10, 10, 10];
    const lows = [10, 10, 10];
    const closes = [10, 10, 10];
    const result = stochasticK(highs, lows, closes, 3);
    expect(result).toEqual([50]);
  });

  it("values are in the range [0, 100]", () => {
    const highs = [15, 16, 17, 18, 19];
    const lows = [10, 11, 12, 13, 14];
    const closes = [12, 13, 15, 16, 17];
    const result = stochasticK(highs, lows, closes, 3);
    result.forEach((v) => {
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(100);
    });
  });

  it("returns length closes.length - period + 1", () => {
    const n = 10;
    const arr = new Array(n).fill(100) as number[];
    expect(stochasticK(arr, arr, arr, 3)).toHaveLength(n - 3 + 1);
  });

  it("returns [] when arrays have mismatched lengths", () => {
    expect(stochasticK([10, 11], [9], [10, 11], 2)).toEqual([]);
  });

  it("returns [] for empty arrays", () => {
    expect(stochasticK([], [], [], 14)).toEqual([]);
  });

  it("returns [] when period exceeds closes length", () => {
    expect(stochasticK([10], [9], [10], 3)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// cumsum
// ---------------------------------------------------------------------------

describe("cumsum", () => {
  it("computes running totals", () => {
    expect(cumsum([1, 2, 3, 4])).toEqual([1, 3, 6, 10]);
  });

  it("handles a single element", () => {
    expect(cumsum([42])).toEqual([42]);
  });

  it("handles negative values", () => {
    expect(cumsum([5, -3, 2])).toEqual([5, 2, 4]);
  });

  it("returns an empty array for empty input", () => {
    expect(cumsum([])).toEqual([]);
  });

  it("handles all zeros", () => {
    expect(cumsum([0, 0, 0])).toEqual([0, 0, 0]);
  });

  it("returns same length as input", () => {
    const input = [10, 20, 30, 40, 50];
    expect(cumsum(input)).toHaveLength(input.length);
  });
});

// ---------------------------------------------------------------------------
// filterNaN / allFinite
// ---------------------------------------------------------------------------

describe("filterNaN", () => {
  it("removes NaN values, preserving finite numbers", () => {
    expect(filterNaN([1, NaN, 2, NaN, 3])).toEqual([1, 2, 3]);
  });

  it("returns all elements when there are no NaNs", () => {
    expect(filterNaN([10, 20, 30])).toEqual([10, 20, 30]);
  });

  it("returns empty array when all values are NaN", () => {
    expect(filterNaN([NaN, NaN, NaN])).toEqual([]);
  });

  it("returns empty array for empty input", () => {
    expect(filterNaN([])).toEqual([]);
  });

  it("preserves Infinity (not NaN)", () => {
    expect(filterNaN([1, Infinity, 2])).toEqual([1, Infinity, 2]);
  });
});

describe("allFinite", () => {
  it("returns true when all values are finite", () => {
    expect(allFinite([1, 2, 3])).toBe(true);
  });

  it("returns false when any value is NaN", () => {
    expect(allFinite([1, NaN, 3])).toBe(false);
  });

  it("returns false when any value is Infinity", () => {
    expect(allFinite([1, Infinity, 3])).toBe(false);
  });

  it("returns false when any value is -Infinity", () => {
    expect(allFinite([1, -Infinity, 3])).toBe(false);
  });

  it("returns true for an empty array (vacuously true)", () => {
    expect(allFinite([])).toBe(true);
  });

  it("returns true for a single finite value", () => {
    expect(allFinite([0])).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// NaN propagation through indicator functions
// ---------------------------------------------------------------------------

describe("NaN handling via filterNaN + indicators", () => {
  it("SMA works correctly after filtering NaN from the input", () => {
    const raw = [1, NaN, 2, 3, NaN, 4, 5];
    const clean = filterNaN(raw); // [1, 2, 3, 4, 5]
    expect(sma(clean, 3)).toEqual([2, 3, 4]);
  });

  it("EMA works correctly after filtering NaN from the input", () => {
    const raw = [10, NaN, 20, 30, NaN, 40];
    const clean = filterNaN(raw); // [10, 20, 30, 40]
    const result = ema(clean, 3);
    expect(result).toHaveLength(2);
    expect(result[0]).toBeCloseTo(20, 6); // SMA seed
  });

  it("allFinite returns false for SMA output when input contained NaN paths", () => {
    // If NaN slips through it would propagate into SMA output
    const direct = sma([1, NaN, 3], 2);
    // NaN in the window → NaN in result
    expect(allFinite(direct)).toBe(false);
  });
});
