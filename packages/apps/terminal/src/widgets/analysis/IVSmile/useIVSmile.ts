/**
 * useIVSmile — TanStack Query hook for IV Smile curve data.
 * Fetches from FlintTrade backend /ft-api/api/v1/iv_smile via POST.
 */

import { useQuery } from "@tanstack/react-query";
import { getFtIVSmile } from "@/services/ftApi";
import { isMarketHours } from "@/lib/market";

export function useIVSmile(
  symbol: string,
  exchange: string,
  expiryDates?: string[],
  isConnected = false,
) {
  return useQuery({
    queryKey: ["ivsmile", symbol, exchange, expiryDates],
    queryFn: () => getFtIVSmile(symbol, exchange, expiryDates),
    enabled: isConnected && Boolean(symbol && exchange),
    refetchInterval: isConnected && isMarketHours() ? 30_000 : false,
    staleTime: 25_000,
  });
}
