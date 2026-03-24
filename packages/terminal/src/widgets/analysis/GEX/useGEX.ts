/**
 * useGEX — TanStack Query hook for Gamma Exposure data.
 * Fetches from FlintTrade backend /ft-api/api/v1/gex via POST.
 */

import { useQuery } from "@tanstack/react-query";
import { getGEXData } from "@/services/ftApi";
import { isMarketHours } from "@/lib/market";

export function useGEX(
  symbol: string,
  exchange: string,
  expiry: string,
  isConnected = false,
) {
  return useQuery({
    queryKey: ["gex", symbol, exchange, expiry],
    queryFn: () => getGEXData(symbol, exchange, expiry || undefined),
    enabled: isConnected && Boolean(symbol && exchange),
    refetchInterval: isConnected && isMarketHours() ? 30_000 : false,
    staleTime: 25_000,
  });
}
