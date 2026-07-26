/**
 * useFiiLongShort — TanStack Query hook for the FII long/short ratio surface.
 * Fetches from the FlintTrade backend /ft-api/api/v1/screener/fii-long-short.
 * (Carried over from the retired FiiLongShort widget.)
 */

import { useQuery } from "@tanstack/react-query";
import { getFiiLongShortData } from "@/services/ftApi";
import { isMarketHours } from "@/lib/market";

export function useFiiLongShort(isConnected = false) {
  return useQuery({
    queryKey: ["fii-long-short"],
    queryFn: () => getFiiLongShortData(),
    enabled: isConnected,
    // FII participant OI updates once daily (post-close), so a long interval is fine.
    refetchInterval: isConnected && isMarketHours() ? 300_000 : false,
    staleTime: 120_000,
  });
}
