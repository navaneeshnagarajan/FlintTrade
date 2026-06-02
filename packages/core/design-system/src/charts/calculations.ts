// Pure indicator calculation functions.
// All functions take OHLCV arrays and return arrays of (number | null)[].
// No React and no chart runtime imports — these are plain math utilities.

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

export type FlintChartTime = string | number | { year: number; month: number; day: number };

export interface FlintChartLineData<TTime = FlintChartTime> {
  time: TTime;
  value: number;
}

export interface FlintChartHistogramData<TTime = FlintChartTime> {
  time: TTime;
  value: number;
  color: string;
}

export interface FlintChartOhlcvBar {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export type OhlcvBar = FlintChartOhlcvBar;

export interface BBResult {
  upper: (number | null)[];
  middle: (number | null)[];
  lower: (number | null)[];
}

export interface SupertrendResult {
  up: (number | null)[];
  down: (number | null)[];
  direction: (1 | -1 | null)[];
}

export interface RSIResult {
  values: (number | null)[];
}

export interface MACDResult {
  macd: (number | null)[];
  signal: (number | null)[];
  hist: (number | null)[];
}

export interface StochResult {
  k: (number | null)[];
  d: (number | null)[];
}

export interface ATRResult {
  values: (number | null)[];
}

export interface ADXResult {
  adx: (number | null)[];
  plusDI: (number | null)[];
  minusDI: (number | null)[];
}

export interface IchimokuResult {
  tenkan: (number | null)[];
  kijun: (number | null)[];
  senkouA: (number | null)[];
  senkouB: (number | null)[];
  chikou: (number | null)[];
}

export interface PivotResult {
  pp: number;
  r1: number;
  r2: number;
  r3: number;
  s1: number;
  s2: number;
  s3: number;
}

export interface KeltnerResult {
  upper: (number | null)[];
  middle: (number | null)[];
  lower: (number | null)[];
}

// ---------------------------------------------------------------------------
// Moving averages
// ---------------------------------------------------------------------------

export function calcEMA(closes: number[], period: number): (number | null)[] {
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

export function calcSMA(closes: number[], period: number): (number | null)[] {
  const result: (number | null)[] = new Array(closes.length).fill(null);
  for (let i = period - 1; i < closes.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += closes[j];
    result[i] = sum / period;
  }
  return result;
}

export function calcWMA(closes: number[], period: number): (number | null)[] {
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

export function calcDEMA(closes: number[], period = 20): (number | null)[] {
  const ema1 = calcEMA(closes, period);
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

export function calcHullMA(closes: number[], period = 20): (number | null)[] {
  const half = Math.floor(period / 2);
  const sqrtP = Math.round(Math.sqrt(period));
  const wmaFull = calcWMA(closes, period);
  const wmaHalf = calcWMA(closes, half);
  const n = closes.length;
  const diff: (number | null)[] = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    if (wmaHalf[i] !== null && wmaFull[i] !== null) {
      diff[i] = 2 * wmaHalf[i]! - wmaFull[i]!;
    }
  }
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

// ---------------------------------------------------------------------------
// Bands / channels
// ---------------------------------------------------------------------------

export function calcBollingerBands(closes: number[], period = 20, mult = 2): BBResult {
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

export function calcKeltnerChannels(
  bars: FlintChartOhlcvBar[],
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

// ---------------------------------------------------------------------------
// Trend
// ---------------------------------------------------------------------------

export function calcSupertrend(
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

export function calcParabolicSAR(
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

export function calcPivotPoints(bars: FlintChartOhlcvBar[]): PivotResult | null {
  if (bars.length < 2) return null;
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

// ---------------------------------------------------------------------------
// Volume-based
// ---------------------------------------------------------------------------

export function calcVWAP<TTime = FlintChartTime>(
  bars: FlintChartOhlcvBar[],
  times: TTime[],
): (number | null)[] {
  const result: (number | null)[] = new Array(bars.length).fill(null);
  let cumulativePV = 0;
  let cumulativeV = 0;
  let lastDay = "";

  for (let i = 0; i < bars.length; i++) {
    const t = times[i];
    const ts = typeof t === "number" ? t : 0;
    const d = new Date(ts * 1000);
    const day = `${d.getUTCFullYear()}-${d.getUTCMonth()}-${d.getUTCDate()}`;
    if (day !== lastDay) {
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

export function calcVWMA(bars: FlintChartOhlcvBar[], period = 20): (number | null)[] {
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

export function calcOBV(closes: number[], volumes: number[]): (number | null)[] {
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

// ---------------------------------------------------------------------------
// Oscillators
// ---------------------------------------------------------------------------

export function calcRSI(closes: number[], period = 14): RSIResult {
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

export function calcMACD(
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

export function calcStochastic(
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

  const smoothK: (number | null)[] = new Array(n).fill(null);
  for (let i = kPeriod + smooth - 2; i < n; i++) {
    let sum = 0;
    let count = 0;
    for (let j = i - smooth + 1; j <= i; j++) {
      if (rawK[j] !== null) { sum += rawK[j]!; count++; }
    }
    if (count === smooth) smoothK[i] = sum / smooth;
  }

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

export function calcATR(
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

export function calcADX(
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

export function calcWilliamsR(
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

export function calcCCI(
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

export function calcIchimoku(
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

// ---------------------------------------------------------------------------
// Data builders (convert raw arrays to lightweight-charts data shapes)
// ---------------------------------------------------------------------------

export function buildLineData<TTime = FlintChartTime>(
  times: TTime[],
  values: (number | null)[],
): FlintChartLineData<TTime>[] {
  const out: FlintChartLineData<TTime>[] = [];
  for (let i = 0; i < times.length; i++) {
    if (values[i] !== null) {
      out.push({ time: times[i], value: values[i]! });
    }
  }
  return out;
}

export function buildHistData<TTime = FlintChartTime>(
  times: TTime[],
  values: (number | null)[],
): FlintChartHistogramData<TTime>[] {
  const out: FlintChartHistogramData<TTime>[] = [];
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
