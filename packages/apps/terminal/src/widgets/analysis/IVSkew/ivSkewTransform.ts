/**
 * ivSkewTransform — pure helpers that turn live OpenAlgo option chains into the
 * `IVSkewData` shape the IVSkew widget renders.
 *
 * Kept separate from the widget so the financial maths (IV normalisation, ATM
 * selection, 25-delta skew) is unit-tested without a broker connection.
 */

import type { ChainEntry, RawOptionRow, RawOptionChain } from "@/widgets/analysis/OptionChain/types";
import type { IVSkewCurve, IVSkewData, IVSkewPoint } from "./IVSkewWidget";

/**
 * Normalise an option row's implied volatility to a 0–1 decimal.
 *
 * OpenAlgo adapters report IV either as a percentage (e.g. `14.8`) or already
 * as a decimal (e.g. `0.148`). Indian index-option IVs sit roughly in the
 * 5–60 % band, so a value above 1.5 is unambiguously a percentage and is
 * divided by 100; anything at or below 1.5 is treated as an existing decimal.
 * Returns 0 when no IV is present (the widget filters out non-positive IVs).
 */
export function normaliseIv(row: RawOptionRow | null | undefined): number {
  if (!row) return 0;
  const raw = row.iv ?? row.implied_volatility ?? 0;
  if (!Number.isFinite(raw) || raw <= 0) return 0;
  return raw > 1.5 ? raw / 100 : raw;
}

/**
 * 25-delta skew = IV of the ~25Δ put − IV of the ~25Δ call (decimal).
 *
 * Picks the call whose delta is closest to +0.25 and the put whose |delta| is
 * closest to 0.25, using each leg's own IV. Returns 0 when deltas are absent
 * (honest: an unknown skew is reported as flat rather than fabricated).
 */
export function skew25Delta(chain: ChainEntry[]): number {
  let callIv: number | null = null;
  let putIv: number | null = null;
  let bestCall = Infinity;
  let bestPut = Infinity;

  for (const entry of chain) {
    const cDelta = entry.ce?.delta;
    const pDelta = entry.pe?.delta;
    const cIv = normaliseIv(entry.ce);
    const pIv = normaliseIv(entry.pe);
    if (cDelta != null && Number.isFinite(cDelta) && cIv > 0) {
      const d = Math.abs(cDelta - 0.25);
      if (d < bestCall) {
        bestCall = d;
        callIv = cIv;
      }
    }
    if (pDelta != null && Number.isFinite(pDelta) && pIv > 0) {
      const d = Math.abs(Math.abs(pDelta) - 0.25);
      if (d < bestPut) {
        bestPut = d;
        putIv = pIv;
      }
    }
  }

  if (callIv == null || putIv == null) return 0;
  return putIv - callIv;
}

/** Strike in `points` nearest to `spot` (ATM fallback when the chain omits it). */
function nearestStrike(points: IVSkewPoint[], spot: number): number {
  let best = points[0].strike;
  let bestDist = Infinity;
  for (const p of points) {
    const d = Math.abs(p.strike - spot);
    if (d < bestDist) {
      bestDist = d;
      best = p.strike;
    }
  }
  return best;
}

/** Build a single expiry's skew curve from a raw chain, or null if unusable. */
export function curveFromChain(expiry: string, raw: RawOptionChain): IVSkewCurve | null {
  const entries: ChainEntry[] = raw.chain ?? [];
  if (entries.length === 0) return null;

  const spot = raw.underlying_ltp && raw.underlying_ltp > 0 ? raw.underlying_ltp : 0;

  const points: IVSkewPoint[] = entries
    .map((entry) => ({
      strike: entry.strike,
      moneyness: spot > 0 ? entry.strike / spot : 1,
      call_iv: normaliseIv(entry.ce),
      put_iv: normaliseIv(entry.pe),
    }))
    .filter((p) => p.call_iv > 0 || p.put_iv > 0)
    .sort((a, b) => a.strike - b.strike);

  if (points.length === 0) return null;

  const atmStrike =
    raw.atm_strike && raw.atm_strike > 0 ? raw.atm_strike : nearestStrike(points, spot);
  const atmPoint = points.find((p) => p.strike === atmStrike);
  // ATM IV: prefer the call leg, fall back to the put leg, then the nearest point.
  const atmIv = atmPoint
    ? atmPoint.call_iv > 0
      ? atmPoint.call_iv
      : atmPoint.put_iv
    : 0;

  return {
    expiry,
    atm_strike: atmStrike,
    atm_iv: atmIv,
    skew_25delta: skew25Delta(entries),
    points,
  };
}

/**
 * Assemble live `IVSkewData` from per-expiry raw chains. Returns null when no
 * expiry yields a usable curve, so the caller can fall back to sample data.
 */
export function buildIVSkewData(
  symbol: string,
  chains: ReadonlyArray<{ expiry: string; raw: RawOptionChain }>,
  updatedAt: string,
): IVSkewData | null {
  const curves: IVSkewCurve[] = [];
  let spot = 0;
  for (const { expiry, raw } of chains) {
    const curve = curveFromChain(expiry, raw);
    if (curve) {
      curves.push(curve);
      if (spot === 0 && raw.underlying_ltp && raw.underlying_ltp > 0) {
        spot = raw.underlying_ltp;
      }
    }
  }
  if (curves.length === 0) return null;
  return { symbol, spot, curves, updated_at: updatedAt };
}
