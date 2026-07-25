/**
 * useIndexContribution — TanStack Query hook for the index-contribution
 * decomposition (W7). Fetches from /ft-api/v1/index-contribution.
 * (Carried over from the retired IndexContribution widget.)
 */

import { useQuery } from "@tanstack/react-query";
import { getIndexContribution } from "@/services/ftApi";
import { isMarketHours } from "@/lib/market";

export function useIndexContribution(index: string, isConnected = false) {
  return useQuery({
    queryKey: ["index-contribution", index],
    queryFn: () => getIndexContribution(index),
    enabled: isConnected && Boolean(index),
    refetchInterval: isConnected && isMarketHours() ? 30_000 : false,
    staleTime: 25_000,
  });
}
