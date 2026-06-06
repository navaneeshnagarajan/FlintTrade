/**
 * ivSkewTransform — pure helper that maps the screener IV-smile response
 * (`IVSmileData`, the SAME live source the IVSmile and GreeksSurface widgets
 * use) into the `IVSkewData` shape the IVSkew widget renders.
 *
 * IMPORTANT: per-strike implied volatility is NOT carried in the OpenAlgo
 * `optionchain` feed (that payload has only ltp/bid/ask/oi). IV lives in the
 * dedicated IV-smile endpoint, so the skew curves must come from `getFtIVSmile`
 * — never derived from the raw chain.
 *
 * Kept separate from the widget so the mapping/normalisation is unit-tested
 * without a broker connection.
 */

import type { IVSmileData } from "@/types/api";
import type { IVSkewCurve, IVSkewData, IVSkewPoint } from "./IVSkewWidget";

/**
 * Normalise an implied-volatility figure to a 0–1 decimal.
 *
 * The screener reports IV as a decimal (e.g. `0.148`), but guard defensively:
 * a value above 1.5 is unambiguously a percentage (Indian index-option IVs sit
 * in the 5–60 % band) and is divided by 100.
 */
export function normaliseIv(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return 0;
  return value > 1.5 ? value / 100 : value;
}

/** Map one IV-smile curve to a skew curve, or null when it has no points. */
function mapCurve(curve: IVSmileData["curves"][number]): IVSkewCurve | null {
  const points: IVSkewPoint[] = (curve.points ?? [])
    .map((p) => ({
      strike: p.strike,
      moneyness: p.moneyness,
      call_iv: normaliseIv(p.call_iv),
      put_iv: normaliseIv(p.put_iv),
    }))
    .filter((p) => p.call_iv > 0 || p.put_iv > 0);

  if (points.length === 0) return null;

  return {
    expiry: curve.expiry,
    atm_strike: curve.atm_strike,
    atm_iv: normaliseIv(curve.atm_iv),
    // skew_25delta is computed server-side (decimal, can be negative) — pass through.
    skew_25delta: Number.isFinite(curve.skew_25delta) ? curve.skew_25delta : 0,
    points,
  };
}

/**
 * Map a live `IVSmileData` payload to `IVSkewData`. Returns null when no curve
 * yields usable points, so the caller can fall back to sample data.
 */
export function mapIVSmileToSkew(
  iv: IVSmileData | null | undefined,
  updatedAt: string,
): IVSkewData | null {
  if (!iv?.curves?.length) return null;

  const curves: IVSkewCurve[] = [];
  for (const curve of iv.curves) {
    const mapped = mapCurve(curve);
    if (mapped) curves.push(mapped);
  }
  if (curves.length === 0) return null;

  return {
    symbol: iv.underlying,
    spot: iv.spot_price,
    curves,
    updated_at: updatedAt,
  };
}
