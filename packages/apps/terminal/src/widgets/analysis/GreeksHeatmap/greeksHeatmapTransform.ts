/**
 * greeksHeatmapTransform — pure helper that turns the screener IV-smile response
 * (`IVSmileData`) into the `ExpiryRow[]` grid the GreeksHeatmap widget renders.
 *
 * IMPORTANT: greeks are NOT carried in the OpenAlgo `optionchain` feed (that
 * payload has only ltp/bid/ask/oi). The live IV smile is the dedicated source;
 * the per-strike greeks are derived from it through the shared Black–Scholes
 * module (`@/lib/optionsMath`) — the same one GreeksSurface's live and sample
 * paths call — so every greek the terminal renders comes from one implementation.
 *
 * Kept separate from the widget so the chain→grid maths (strike alignment, ATM
 * classification, greek derivation) is unit-tested without a broker connection.
 */

import { bsGreeks, normaliseIv, yearsFromDays } from "@/lib/optionsMath";
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
 * Call-side option greeks for one strike, from an IV figure (decimal) and a
 * days-to-expiry count. A thin adapter over the shared `bsGreeks` — the ATM
 * strike stands in for spot, since the IV-smile curve carries no per-curve spot.
 *
 * Scale conventions come from `@/lib/optionsMath`: gamma ×1000, theta per day,
 * vega per 1 percentage-point IV move. Degenerate input (non-positive IV, ATM,
 * strike or dte) returns all zeros — with no time value the whole cell is
 * reported inert (delta 0 too) rather than a lone delta that would look
 * meaningful inside a "Live" grid.
 *
 * @param strike Contract strike.
 * @param atmStrike The curve's ATM strike, used as the spot proxy.
 * @param ivDecimal Implied volatility as a decimal fraction.
 * @param dte Days to expiry.
 * @returns Display-rounded delta, gamma, theta and vega.
 */
export function approxGreeks(
  strike: number,
  atmStrike: number,
  ivDecimal: number,
  dte: number,
): Greeks {
  const { delta, gamma, theta, vega } = bsGreeks({
    spot: atmStrike,
    strike,
    timeToExpiryYears: yearsFromDays(dte),
    volatility: ivDecimal,
    optionType: "call",
  });
  return {
    delta: Number(delta.toFixed(4)),
    gamma: Number(gamma.toFixed(6)),
    theta: Number(theta.toFixed(2)),
    vega: Number(vega.toFixed(4)),
  };
}

/**
 * Classify a strike against the ATM strike on the call convention.
 *
 * @param strike Contract strike.
 * @param atm The curve's ATM strike.
 * @returns "ATM" on an exact match, otherwise "ITM" below ATM and "OTM" above.
 */
export function classifyMoneyness(strike: number, atm: number): Moneyness {
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
  // Drop degenerate expiries upfront: a non-positive days-to-expiry produces
  // all-zero time-decay greeks, so such a row must never appear in a "Live"
  // grid (even alongside viable rows).
  const curves = (iv?.curves ?? []).filter((c) => c.days_to_expiry > 0);
  if (curves.length === 0) return null;

  // Per-curve: strike → mid-IV (decimal), keeping only strikes with positive IV.
  const perCurve = curves.map((curve) => {
    const ivByStrike = new Map<number, number>();
    for (const p of curve.points ?? []) {
      const callIv = normaliseIv(p.call_iv);
      const putIv = normaliseIv(p.put_iv);
      if (callIv > 0 && putIv > 0) {
        ivByStrike.set(p.strike, (callIv + putIv) / 2);
      }
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
