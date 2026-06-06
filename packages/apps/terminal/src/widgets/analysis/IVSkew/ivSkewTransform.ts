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
 * Normalise a single implied-volatility figure to a 0–1 decimal.
 *
 * The screener reports IV in PERCENT (e.g. `14.8` = 14.8 %), so a value above
 * 1.5 is divided by 100; a value already in decimal form (≤ 1.5) is left as-is.
 */
export function normaliseIv(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return 0;
  return value > 1.5 ? value / 100 : value;
}

/**
 * Map one IV-smile curve to a skew curve, or null when it has no points.
 *
 * IV figures from the screener are in PERCENT (call_iv/put_iv/atm_iv ≈ 14.8) and
 * the 25Δ skew is in percentage POINTS (≈ 2.0). The widget renders all of these
 * by multiplying the stored value by 100, so a single ÷100 scale (detected from
 * the curve's IV magnitude) is applied UNIFORMLY to the IVs AND the skew — a
 * per-value `>1.5` test would correctly scale a 2.0 skew but wrongly leave a
 * small 0.5 percentage-point skew, so the curve-level scale keeps them coherent.
 */
function mapCurve(curve: IVSmileData["curves"][number]): IVSkewCurve | null {
  const raw = (curve.points ?? []).filter((p) => p.call_iv > 0 || p.put_iv > 0);
  if (raw.length === 0) return null;

  // Detect percent vs decimal from the largest IV the curve carries.
  const maxIv = Math.max(
    Number.isFinite(curve.atm_iv) ? curve.atm_iv : 0,
    ...raw.flatMap((p) => [p.call_iv, p.put_iv]),
  );
  const scale = maxIv > 1.5 ? 1 / 100 : 1;

  const points: IVSkewPoint[] = raw
    .map((p) => ({
      strike: p.strike,
      moneyness: p.moneyness,
      call_iv: Math.max(0, p.call_iv) * scale,
      put_iv: Math.max(0, p.put_iv) * scale,
    }))
    .filter((p) => p.call_iv > 0 || p.put_iv > 0);

  if (points.length === 0) return null;

  return {
    expiry: curve.expiry,
    atm_strike: curve.atm_strike,
    atm_iv: (Number.isFinite(curve.atm_iv) ? Math.max(0, curve.atm_iv) : 0) * scale,
    // skew shares the IVs' units (percentage points) — apply the same scale so
    // it renders as e.g. +2.00 %, not +200 %. Can be negative (call premium).
    skew_25delta: (Number.isFinite(curve.skew_25delta) ? curve.skew_25delta : 0) * scale,
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
