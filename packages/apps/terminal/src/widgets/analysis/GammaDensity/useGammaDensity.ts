/**
 * useGammaDensity — TanStack Query hook for the gamma density surface (DP2).
 * Fetches from the FlintTrade backend /ft-api/api/v1/gammadensity via POST.
 */

import { useQuery } from "@tanstack/react-query";
import { getGammaDensityData } from "@/services/ftApi";
import { isMarketHours } from "@/lib/market";

export function useGammaDensity(
  symbol: string,
  exchange: string,
  expiry: string,
  isConnected = false,
) {
  return useQuery({
    queryKey: ["gamma-density", symbol, exchange, expiry],
    queryFn: () => getGammaDensityData(symbol, exchange, expiry),
    enabled: isConnected && Boolean(symbol && exchange && expiry),
    refetchInterval: isConnected && Boolean(expiry) && isMarketHours() ? 30_000 : false,
    staleTime: 25_000,
  });
}
