/**
 * useOIProfile — TanStack Query hook for OI Profile data.
 * Fetches from FlintTrade backend /ft-api/api/v1/oiprofile via POST.
 */

import { useQuery } from "@tanstack/react-query";
import { getOIProfile } from "@/services/ftApi";
import { isMarketHours } from "@/lib/market";

export function useOIProfile(
  symbol: string,
  exchange: string,
  expiryDate: string,
  strikeCount?: number,
) {
  return useQuery({
    queryKey: ["oiprofile", symbol, exchange, expiryDate, strikeCount],
    queryFn: () => getOIProfile(symbol, exchange, expiryDate, strikeCount),
    enabled: Boolean(symbol && exchange && expiryDate),
    refetchInterval: isMarketHours() ? 30_000 : false,
    staleTime: 25_000,
  });
}
