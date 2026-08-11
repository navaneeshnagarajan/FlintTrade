import { useQuery } from "@tanstack/react-query";
import { getPositionbook } from "@/services/api";
import type { Position } from "@/types/api";
import { isMarketHours } from "@/lib/market";
import { queryKeys } from "@/services/queryKeys";
import {
  useAccountReadContext,
  type AccountReadContext,
} from "@/hooks/useAccountReadsEnabled";

interface BrokerDataQueryOptions {
  enabled?: boolean;
  context?: AccountReadContext;
}

/**
 * Pure TanStack Query hook for the PositionBook REST endpoint.
 *
 * Scope, scheduling, and transport all come from one immutable account-read
 * context. The transport never re-selects a different account from mutable
 * stores after the query has already claimed its cache key.
 */
export function usePositions(options: BrokerDataQueryOptions = {}) {
  const currentContext = useAccountReadContext();
  const context = options.context ?? currentContext;
  const enabled = (options.enabled ?? true) && context.enabled;
  return useQuery<Position[]>({
    queryKey: queryKeys.positions.list(context.identity.scopeKey),
    queryFn: ({ signal }) => getPositionbook(context, signal),
    enabled,
    retry: false,
    staleTime: 3_000,
    refetchInterval: () => (enabled ? (isMarketHours() ? 5_000 : 60_000) : false),
  });
}
