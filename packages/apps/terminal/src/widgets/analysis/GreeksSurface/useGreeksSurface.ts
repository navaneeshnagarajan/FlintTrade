/**
 * useGreeksSurface — data hook combining IV Smile and Option Chain
 * to compute a per-expiry, per-moneyness Greeks surface.
 *
 * When connected: fetches live IV smile + option chain data.
 * When disconnected: caller falls back to sample data.
 */

import { useQuery } from "@tanstack/react-query";
import { getFtIVSmile } from "@/services/ftApi";
import { getOptionChain } from "@/services/api";
import { isMarketHours } from "@/lib/market";
import type { GreeksSurfaceExpiry, GreeksSurfacePoint } from "./sampleData";

const MONEYNESS_RANGE = 0.05; // ±5% from ATM
const MONEYNESS_STEPS = 11;   // -5% to +5% in 1% increments

/** Result shape: the derived surface plus the source payload's honesty flag. */
export interface GreeksSurfaceResult {
  expiries: GreeksSurfaceExpiry[];
  /** True when the source IV smile payload was flagged `is_sample_data`. */
  isSampleData: boolean;
}

/**
 * Treat anything except an explicit backend `is_sample_data: false` as sample
 * or otherwise untrusted provenance.
 */
function carriesSampleFlag(payload: unknown): boolean {
  return !(
    typeof payload === "object" &&
    payload !== null &&
    (payload as { is_sample_data?: unknown }).is_sample_data === false
  );
}

export function buildSurfaceFromIVSmile(
  ivData: Awaited<ReturnType<typeof getFtIVSmile>>,
): GreeksSurfaceExpiry[] {
  if (!ivData?.curves?.length) return [];

  return ivData.curves.flatMap((curve) => {
    const { expiry, days_to_expiry, atm_strike, points: ivPoints } = curve;
    const completePoints = ivPoints.filter(
      (point) => Number.isFinite(point.strike) && point.strike > 0
        && Number.isFinite(point.call_iv) && point.call_iv > 0
        && Number.isFinite(point.put_iv) && point.put_iv > 0,
    );
    if (!(days_to_expiry > 0) || !(atm_strike > 0) || completePoints.length === 0) return [];

    const surfacePoints: GreeksSurfacePoint[] = [];
    for (let i = 0; i < MONEYNESS_STEPS; i++) {
      const mv = -MONEYNESS_RANGE + i * (MONEYNESS_RANGE * 2 / (MONEYNESS_STEPS - 1));
      const moneynessLabel =
        mv === 0 ? "ATM"
        : mv > 0 ? `+${(mv * 100).toFixed(0)}%`
        : `${(mv * 100).toFixed(0)}%`;
      const targetStrike = Math.round(atm_strike * (1 + mv) / 50) * 50;

      // Find nearest strike in iv points
      const nearest = completePoints.reduce((best, p) => {
        return Math.abs(p.strike - targetStrike) < Math.abs(best.strike - targetStrike)
          ? p : best;
      }, completePoints[0]);

      const ivDec = (nearest.call_iv + nearest.put_iv) / 2;
      if (!(ivDec > 0) || !Number.isFinite(ivDec)) continue;
      const iv = ivDec * 100;
      // Approximate greeks from IV and moneyness
      const T = days_to_expiry / 365;
      const d1 = T > 0
        ? (-mv + 0.5 * ivDec * ivDec * T) / (ivDec * Math.sqrt(T))
        : (mv >= 0 ? 3 : -3);
      const delta = 1 / (1 + Math.exp(-1.7 * d1));
      const pdf = Math.exp(-0.5 * d1 * d1) / Math.sqrt(2 * Math.PI);
      const gamma = T > 0 ? (pdf / (targetStrike * ivDec * Math.sqrt(T))) * 1000 : 0;
      const theta = T > 0
        ? -(ivDec * atm_strike * Math.exp(-0.5 * mv * mv * 100)) / Math.sqrt(365 * days_to_expiry * 2 * Math.PI)
        : 0;

      surfacePoints.push({
        moneyness: moneynessLabel,
        moneynessVal: mv,
        strike: targetStrike,
        iv: parseFloat(iv.toFixed(2)),
        delta: parseFloat(delta.toFixed(4)),
        gamma: parseFloat(gamma.toFixed(6)),
        theta: parseFloat(theta.toFixed(2)),
      });
    }

    if (surfacePoints.length === 0) return [];
    return [{
      expiry,
      label: `${expiry} (${days_to_expiry}d)`,
      dte: days_to_expiry,
      points: surfacePoints,
    }];
  });
}

export function useGreeksSurface(
  symbol: string,
  exchange: string,
  expiryDates: string[] | undefined,
  isConnected: boolean,
) {
  return useQuery({
    queryKey: ["greekssurface", symbol, exchange, expiryDates],
    queryFn: async (): Promise<GreeksSurfaceResult> => {
      const [ivData] = await Promise.all([
        getFtIVSmile(symbol, exchange, expiryDates),
        // Option chain can be used later for more precise greeks
        getOptionChain(symbol, exchange),
      ]);
      return {
        expiries: buildSurfaceFromIVSmile(ivData),
        // Carry the source payload's honesty flag through the derivation so
        // the widget can badge a surface built from fabricated sample IVs.
        isSampleData: carriesSampleFlag(ivData),
      };
    },
    enabled: isConnected && Boolean(symbol && exchange),
    refetchInterval: isConnected && isMarketHours() ? 30_000 : false,
    staleTime: 25_000,
  });
}
