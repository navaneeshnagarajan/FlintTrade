/**
 * useOIProfile — TanStack Query hook for OI Profile data.
 * Fetches from FlintTrade backend /ft-api/api/v1/oiprofile via POST.
 */

import { useQuery } from "@tanstack/react-query";
import { getFtOIProfile } from "@/services/ftApi";
import { isMarketHours } from "@/lib/market";

export function useOIProfile(
  symbol: string,
  exchange: string,
  expiryDate: string,
  strikeCount?: number,
  isConnected = false,
) {
  return useQuery({
    queryKey: ["oiprofile", symbol, exchange, expiryDate, strikeCount],
    queryFn: () => getFtOIProfile(symbol, exchange, expiryDate, strikeCount),
    enabled: isConnected && Boolean(symbol && exchange && expiryDate),
    refetchInterval: isConnected && isMarketHours() ? 30_000 : false,
    staleTime: 25_000,
  });
}
