/**
 * usePatternDetection — TanStack Query hook for candlestick pattern detection
 * (W4). When connected it fetches the symbol's recent daily bars from the
 * OpenAlgo bridge history and posts them to the detection endpoint, so the
 * scan is genuinely live; disconnected callers fall back to the sample scan.
 */

import { useQuery } from "@tanstack/react-query";
import { getHistory } from "@/services/api";
import { getCandlestickPatterns } from "@/services/ftApi";
import type { CandlestickPatternResponse } from "@/types/api";
import { isMarketHours } from "@/lib/market";

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

export function usePatternDetection(
  symbol: string,
  exchange: string,
  isConnected = false,
) {
  return useQuery<CandlestickPatternResponse>({
    queryKey: ["pattern-detection", symbol, exchange],
    queryFn: async () => {
      const bars = await getHistory(symbol, exchange, "D", isoDaysAgo(120), isoDaysAgo(0));
      const mapped = (bars ?? []).map((b) => ({
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
        time: new Date(b.timestamp * 1000).toISOString().slice(0, 10),
      }));
      return getCandlestickPatterns(mapped);
    },
    enabled: isConnected && Boolean(symbol),
    refetchInterval: isConnected && isMarketHours() ? 60_000 : false,
    staleTime: 55_000,
  });
}
