/**
 * ivSkewTransform — pure helper that maps the screener IV-smile response
 * (`IVSmileData`) into the normalised curve shape the IV Smile widget renders
 * in BOTH of its views (the Plotly smile view and the Flint banded-line skew
 * view).
 *
 * It came from the retired IVSkew widget and is the reason that widget was the
 * safer of the two: the raw payload's IV can arrive either as a decimal
 * fraction (0.148) or as percentage points (14.8) depending on the screener
 * path that produced it, and the widget multiplies by 100 for display. Without
 * the scale detection below, a percentage-points payload renders at 100×.
 *
 * IMPORTANT: per-strike implied volatility is NOT carried in the OpenAlgo
 * `optionchain` feed (that payload has only ltp/bid/ask/oi). IV lives in the
 * dedicated IV-smile endpoint, so the curves must come from `getFtIVSmile` —
 * never derived from the raw chain.
 *
 * Kept separate from the widget so the mapping/normalisation is unit-tested
 * without a broker connection.
 */

import { normaliseIv } from "@/lib/optionsMath";
import type { IVSmileData } from "@/types/api";

/**
 * Normalise a single implied-volatility figure to a 0–1 decimal.
 *
 * Re-exported from the shared options-maths module (`@/lib/optionsMath`), which
 * owns the one percent-vs-fraction heuristic; the widget-local copy is gone.
 */
export { normaliseIv };

/** One strike on a normalised curve. IV is always a 0–1 decimal here. */
export interface NormalisedIVPoint {
  strike: number;
  /** strike / spot */
  moneyness: number;
  /** 0–1 decimal (e.g. 0.18 = 18 %) */
  call_iv: number;
  put_iv: number;
}

/** One expiry's normalised curve. */
export interface NormalisedIVCurve {
  expiry: string;
  atm_strike: number;
  /** decimal */
  atm_iv: number;
  /** put_iv_25d − call_iv_25d, decimal. Negative means a call premium. */
  skew_25delta: number;
  points: NormalisedIVPoint[];
}

/** The render-ready payload both views consume. */
export interface NormalisedIVData {
  symbol: string;
  spot: number;
  curves: NormalisedIVCurve[];
}

/**
 * Map one IV-smile curve to a normalised curve, or null when it has no points.
 *
 * The widget renders decimal IV by multiplying by 100. A single legacy scale,
 * detected from the curve's IV magnitude, is applied uniformly to IV and skew.
 */
function mapCurve(curve: IVSmileData["curves"][number]): NormalisedIVCurve | null {
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

  const points: NormalisedIVPoint[] = raw
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
 * Map a live `IVSmileData` payload to the normalised curve shape. Returns null
 * when no curve yields usable points, so the caller can fail closed rather than
 * render an empty chart as if it were live.
 */
export function mapIVSmileToSkew(
  iv: IVSmileData | null | undefined,
): NormalisedIVData | null {
  if (!iv?.curves?.length) return null;

  const curves: NormalisedIVCurve[] = [];
  for (const curve of iv.curves) {
    const mapped = mapCurve(curve);
    if (mapped) curves.push(mapped);
  }
  if (curves.length === 0) return null;

  return {
    symbol: iv.underlying,
    spot: iv.spot_price,
    curves,
  };
}
