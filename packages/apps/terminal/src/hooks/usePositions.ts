import { useQuery } from "@tanstack/react-query";
import { getPositionbook } from "@/services/api";
import type { Position } from "@/types/api";
import { isMarketHours } from "@/lib/market";
import { queryKeys } from "@/services/queryKeys";
import { useDataScope } from "@/hooks/useDataScope";

interface BrokerDataQueryOptions {
  enabled?: boolean;
}

/**
 * Pure TanStack Query hook for the PositionBook REST endpoint.
 *
 * Does not write into any Zustand store — that mirror is maintained by
 * `useTradingStoreSync` at the app root so there is exactly one write
 * point.
 */
export function usePositions(options: BrokerDataQueryOptions = {}) {
  const enabled = options.enabled ?? true;
  const scope = useDataScope();
  return useQuery<Position[]>({
    queryKey: queryKeys.positions.list(scope),
    queryFn: getPositionbook,
    enabled,
    staleTime: 3_000,
    refetchInterval: () => (enabled ? (isMarketHours() ? 5_000 : 60_000) : false),
  });
}
