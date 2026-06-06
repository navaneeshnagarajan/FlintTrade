/**
 * greeksHeatmapTransform — pure helper that turns the screener IV-smile response
 * (`IVSmileData`) into the `ExpiryRow[]` grid the GreeksHeatmap widget renders.
 *
 * IMPORTANT: greeks are NOT carried in the OpenAlgo `optionchain` feed (that
 * payload has only ltp/bid/ask/oi). The live IV smile is the dedicated source;
 * the per-strike greeks are derived from it with the SAME Black–Scholes
 * approximation the GreeksSurface widget uses (`buildSurfaceFromIVSmile`), so
 * the two widgets stay consistent.
 *
 * Kept separate from the widget so the chain→grid maths (strike alignment, ATM
 * classification, greek derivation) is unit-tested without a broker connection.
 */

import type { IVSmileData } from "@/types/api";

export type Moneyness = "OTM" | "ATM" | "ITM";

export interface HeatCell {
  strike: number;
  moneyness: Moneyness;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
}

export interface ExpiryRow {
  expiry: string;
  label: string;
  dte: number;
  cells: HeatCell[];
}

interface Greeks {
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
}

/**
 * Approximate option greeks from an IV figure (decimal) and time to expiry,
 * mirroring GreeksSurface's `buildSurfaceFromIVSmile`. Call-side greeks; vega is
 * the standard BS sensitivity `φ(d1)·√T`. Returns zeros for non-positive IV.
 */
export function approxGreeks(
  strike: number,
  atmStrike: number,
  ivDecimal: number,
  dte: number,
): Greeks {
  if (!(ivDecimal > 0) || !(atmStrike > 0)) {
    return { delta: 0, gamma: 0, theta: 0, vega: 0 };
  }
  const mv = (strike - atmStrike) / atmStrike; // log-moneyness proxy
  const T = dte / 365;
  // d1: ITM call (strike below ATM, mv<0) → positive d1 → high delta.
  const d1 =
    T > 0 ? (-mv + 0.5 * ivDecimal * ivDecimal * T) / (ivDecimal * Math.sqrt(T)) : mv < 0 ? 3 : -3;
  const delta = 1 / (1 + Math.exp(-1.7 * d1)); // logistic approximation
  const pdf = Math.exp(-0.5 * d1 * d1) / Math.sqrt(2 * Math.PI);
  const gamma = T > 0 ? (pdf / (strike * ivDecimal * Math.sqrt(T))) * 1000 : 0;
  const theta =
    T > 0
      ? -(ivDecimal * atmStrike * Math.exp(-0.5 * mv * mv * 100)) /
        Math.sqrt(365 * dte * 2 * Math.PI)
      : 0;
  const vega = T > 0 ? pdf * Math.sqrt(T) : 0;
  return {
    delta: Number(delta.toFixed(4)),
    gamma: Number(gamma.toFixed(6)),
    theta: Number(theta.toFixed(2)),
    vega: Number(vega.toFixed(4)),
  };
}

function normaliseIv(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return 0;
  return value > 1.5 ? value / 100 : value;
}

function classifyMoneyness(strike: number, atm: number): Moneyness {
  if (strike === atm) return "ATM";
  // Call convention: a strike below ATM is in-the-money for a call.
  return strike < atm ? "ITM" : "OTM";
}

/** Short display label from an expiry string (truncated when long). */
function labelFor(expiry: string): string {
  return expiry.length > 11 ? expiry.slice(0, 11) : expiry;
}

/**
 * Build the aligned greeks grid from a live IV smile. Every expiry row is
 * rendered against the SAME strike set (the intersection of strikes present
 * across all curves) so the grid columns stay aligned. Returns null when no
 * usable strike is shared, so the caller can fall back to sample data.
 */
export function buildGreeksHeatmap(iv: IVSmileData | null | undefined): ExpiryRow[] | null {
  const curves = iv?.curves ?? [];
  if (curves.length === 0) return null;

  // Per-curve: strike → mid-IV (decimal), keeping only strikes with positive IV.
  const perCurve = curves.map((curve) => {
    const ivByStrike = new Map<number, number>();
    for (const p of curve.points ?? []) {
      const mid = (normaliseIv(p.call_iv) + normaliseIv(p.put_iv)) / 2;
      if (mid > 0) ivByStrike.set(p.strike, mid);
    }
    return { curve, ivByStrike };
  });

  // Intersection of strikes carrying IV across every expiry.
  const [first, ...rest] = perCurve;
  let common = [...first.ivByStrike.keys()];
  for (const e of rest) common = common.filter((s) => e.ivByStrike.has(s));
  common.sort((a, b) => a - b);
  if (common.length === 0) return null;

  const rows: ExpiryRow[] = perCurve.map(({ curve, ivByStrike }) => {
    const atm =
      curve.atm_strike && curve.atm_strike > 0
        ? curve.atm_strike
        : common[Math.floor(common.length / 2)];
    const cells: HeatCell[] = common.map((strike) => {
      const g = approxGreeks(strike, atm, ivByStrike.get(strike) ?? 0, curve.days_to_expiry);
      return { strike, moneyness: classifyMoneyness(strike, atm), ...g };
    });
    return {
      expiry: curve.expiry,
      label: labelFor(curve.expiry),
      dte: curve.days_to_expiry,
      cells,
    };
  });

  return rows;
}
