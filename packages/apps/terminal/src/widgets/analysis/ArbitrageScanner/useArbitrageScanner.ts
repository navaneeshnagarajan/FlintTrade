/**
 * useArbitrageScanner — TanStack Query hook for the arbitrage scanner (DP3).
 * Fetches from the FlintTrade backend /ft-api/api/v1/screener/arbitrage via POST.
 *
 * The scan is driven by observed prices. Until a live cash+future universe feed
 * is wired the hook posts an empty request, so the backend returns its clearly
 * flagged sample scan (is_sample_data=true).
 */

import { useQuery } from "@tanstack/react-query";
import { getArbitrageScan } from "@/services/ftApi";
import { isMarketHours } from "@/lib/market";

export function useArbitrageScanner(isConnected = false) {
  return useQuery({
    queryKey: ["arbitrage-scan"],
    queryFn: () => getArbitrageScan(),
    enabled: isConnected,
    refetchInterval: isConnected && isMarketHours() ? 30_000 : false,
    staleTime: 25_000,
  });
}
