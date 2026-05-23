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

function buildSurfaceFromIVSmile(
  ivData: Awaited<ReturnType<typeof getFtIVSmile>>,
): GreeksSurfaceExpiry[] {
  if (!ivData?.curves?.length) return [];

  return ivData.curves.map((curve) => {
    const { expiry, days_to_expiry, atm_strike, points: ivPoints } = curve;

    const surfacePoints: GreeksSurfacePoint[] = [];
    for (let i = 0; i < MONEYNESS_STEPS; i++) {
      const mv = -MONEYNESS_RANGE + i * (MONEYNESS_RANGE * 2 / (MONEYNESS_STEPS - 1));
      const moneynessLabel =
        mv === 0 ? "ATM"
        : mv > 0 ? `+${(mv * 100).toFixed(0)}%`
        : `${(mv * 100).toFixed(0)}%`;
      const targetStrike = Math.round(atm_strike * (1 + mv) / 50) * 50;

      // Find nearest strike in iv points
      const nearest = ivPoints.reduce((best, p) => {
        return Math.abs(p.strike - targetStrike) < Math.abs(best.strike - targetStrike)
          ? p : best;
      }, ivPoints[0]);

      if (!nearest) continue;

      const iv = ((nearest.call_iv + nearest.put_iv) / 2) * 100;
      // Approximate greeks from IV and moneyness
      const T = days_to_expiry / 365;
      const ivDec = iv / 100;
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

    return {
      expiry,
      label: `${expiry} (${days_to_expiry}d)`,
      dte: days_to_expiry,
      points: surfacePoints,
    };
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
    queryFn: async () => {
      const [ivData] = await Promise.all([
        getFtIVSmile(symbol, exchange, expiryDates),
        // Option chain can be used later for more precise greeks
        getOptionChain(symbol, exchange),
      ]);
      return buildSurfaceFromIVSmile(ivData);
    },
    enabled: isConnected && Boolean(symbol && exchange),
    refetchInterval: isConnected && isMarketHours() ? 30_000 : false,
    staleTime: 25_000,
  });
}
