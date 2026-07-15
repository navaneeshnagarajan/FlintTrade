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
 * The current endpoint reports decimal IV. Percentage-point normalisation is
 * retained only for one-way compatibility with older saved/mock payloads.
 */
export function normaliseIv(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return 0;
  return value > 1.5 ? value / 100 : value;
}

/**
 * Map one IV-smile curve to a skew curve, or null when it has no points.
 *
 * The widget renders decimal IV by multiplying by 100. A single legacy scale,
 * detected from the curve's IV magnitude, is applied uniformly to IV and skew.
 */
function mapCurve(curve: IVSmileData["curves"][number]): IVSkewCurve | null {
  const raw = (curve.points ?? []).filter(
    (p) => Number.isFinite(p.call_iv) && p.call_iv > 0
      && Number.isFinite(p.put_iv) && p.put_iv > 0
      && Number.isFinite(p.moneyness) && p.moneyness > 0,
  );
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
    .filter((p) => p.call_iv > 0 && p.put_iv > 0);

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
