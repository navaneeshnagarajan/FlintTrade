import { useQuery } from "@tanstack/react-query";
import { getPositionbook } from "@/services/api";
import type { Position } from "@/types/api";
import { isMarketHours } from "@/lib/market";
import { queryKeys } from "@/services/queryKeys";

/**
 * Pure TanStack Query hook for the PositionBook REST endpoint.
 *
 * Does not write into any Zustand store — that mirror is maintained by
 * `useTradingStoreSync` at the app root so there is exactly one write
 * point.
 */
export function usePositions() {
  return useQuery<Position[]>({
    queryKey: queryKeys.positions.all,
    queryFn: getPositionbook,
    staleTime: 3_000,
    refetchInterval: () => (isMarketHours() ? 5_000 : 60_000),
  });
}
