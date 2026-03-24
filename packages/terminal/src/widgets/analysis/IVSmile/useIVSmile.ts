/**
 * useIVSmile — TanStack Query hook for IV Smile curve data.
 * Fetches from FlintTrade backend /ft-api/api/v1/iv_smile via POST.
 */

import { useQuery } from "@tanstack/react-query";
import { getIVSmile } from "@/services/ftApi";
import { isMarketHours } from "@/lib/market";

export function useIVSmile(
  symbol: string,
  exchange: string,
  expiryDates?: string[],
) {
  return useQuery({
    queryKey: ["ivsmile", symbol, exchange, expiryDates],
    queryFn: () => getIVSmile(symbol, exchange, expiryDates),
    enabled: Boolean(symbol && exchange),
    refetchInterval: isMarketHours() ? 30_000 : false,
    staleTime: 25_000,
  });
}
