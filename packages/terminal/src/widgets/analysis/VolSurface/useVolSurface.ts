/**
 * useVolSurface — TanStack Query hook for 3D Volatility Surface data.
 * Fetches from FlintTrade backend /ft-api/api/v1/volsurface via POST.
 */

import { useQuery } from "@tanstack/react-query";
import { getVolSurface } from "@/services/ftApi";
import { isMarketHours } from "@/lib/market";

export function useVolSurface(
  symbol: string,
  exchange: string,
  expiryDates: string[],
  strikeCount?: number,
) {
  return useQuery({
    queryKey: ["volsurface", symbol, exchange, expiryDates, strikeCount],
    queryFn: () => getVolSurface(symbol, exchange, expiryDates, strikeCount),
    enabled: Boolean(symbol && exchange && expiryDates.length >= 1),
    refetchInterval: isMarketHours() ? 30_000 : false,
    staleTime: 25_000,
  });
}
