/**
 * Pivot point calculation logic.
 * Supports: Standard, Fibonacci, Woodie's, Camarilla, DeMark.
 */

export interface PivotLevels {
  p: number;
  r1: number;
  r2: number;
  r3: number;
  r4: number;
  s1: number;
  s2: number;
  s3: number;
  s4: number;
}

export type PivotMethod = "standard" | "fibonacci" | "woodie" | "camarilla" | "demark";

export const PIVOT_METHODS: PivotMethod[] = [
  "standard",
  "fibonacci",
  "woodie",
  "camarilla",
  "demark",
];

export const METHOD_LABELS: Record<PivotMethod, string> = {
  standard: "Standard",
  fibonacci: "Fibonacci",
  woodie: "Woodie",
  camarilla: "Camarilla",
  demark: "DeMark",
};

function round2(v: number): number {
  return Math.round(v * 100) / 100;
}

export function calcPivots(
  high: number,
  low: number,
  close: number,
  open: number,
  method: PivotMethod,
): PivotLevels {
  const range = high - low;

  switch (method) {
    case "standard": {
      const p = (high + low + close) / 3;
      return {
        p: round2(p),
        r1: round2(2 * p - low),
        r2: round2(p + range),
        r3: round2(high + 2 * (p - low)),
        r4: round2(p + 3 * range),
        s1: round2(2 * p - high),
        s2: round2(p - range),
        s3: round2(low - 2 * (high - p)),
        s4: round2(p - 3 * range),
      };
    }
    case "fibonacci": {
      const p = (high + low + close) / 3;
      return {
        p: round2(p),
        r1: round2(p + 0.382 * range),
        r2: round2(p + 0.618 * range),
        r3: round2(p + range),
        r4: round2(p + 1.618 * range),
        s1: round2(p - 0.382 * range),
        s2: round2(p - 0.618 * range),
        s3: round2(p - range),
        s4: round2(p - 1.618 * range),
      };
    }
    case "woodie": {
      const p = (high + low + 2 * close) / 4;
      return {
        p: round2(p),
        r1: round2(2 * p - low),
        r2: round2(p + range),
        r3: round2(high + 2 * (p - low)),
        r4: round2(p + 2 * range),
        s1: round2(2 * p - high),
        s2: round2(p - range),
        s3: round2(low - 2 * (high - p)),
        s4: round2(p - 2 * range),
      };
    }
    case "camarilla": {
      const p = (high + low + close) / 3;
      return {
        p: round2(p),
        r1: round2(close + range * 1.1 / 12),
        r2: round2(close + range * 1.1 / 6),
        r3: round2(close + range * 1.1 / 4),
        r4: round2(close + range * 1.1 / 2),
        s1: round2(close - range * 1.1 / 12),
        s2: round2(close - range * 1.1 / 6),
        s3: round2(close - range * 1.1 / 4),
        s4: round2(close - range * 1.1 / 2),
      };
    }
    case "demark": {
      let x: number;
      if (close < open) x = high + 2 * low + close;
      else if (close > open) x = 2 * high + low + close;
      else x = high + low + 2 * close;
      const p = x / 4;
      return {
        p: round2(p),
        r1: round2(x / 2 - low),
        r2: round2(x / 2 - low + (high - low) * 0.5),
        r3: round2(x / 2 - low + (high - low)),
        r4: round2(x / 2 - low + (high - low) * 1.5),
        s1: round2(x / 2 - high),
        s2: round2(x / 2 - high - (high - low) * 0.5),
        s3: round2(x / 2 - high - (high - low)),
        s4: round2(x / 2 - high - (high - low) * 1.5),
      };
    }
  }
}


/**
 * Returns which zone a price is in relative to pivot levels.
 * "above_r4" | "r3_r4" | "r2_r3" | "r1_r2" | "p_r1" | "s1_p" | "s2_s1" | "s3_s2" | "s4_s3" | "below_s4"
 */
export function getPriceZone(price: number, levels: PivotLevels): string {
  if (price >= levels.r4) return "above_r4";
  if (price >= levels.r3) return "r3_r4";
  if (price >= levels.r2) return "r2_r3";
  if (price >= levels.r1) return "r1_r2";
  if (price >= levels.p) return "p_r1";
  if (price >= levels.s1) return "s1_p";
  if (price >= levels.s2) return "s2_s1";
  if (price >= levels.s3) return "s3_s2";
  if (price >= levels.s4) return "s4_s3";
  return "below_s4";
}
