import { useQuery } from "@tanstack/react-query";
import { getFunds } from "@/services/api";
import type { Funds } from "@/types/api";
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
 * Pure TanStack Query hook for the Funds REST endpoint. Query key, scheduling,
 * and transport are bound to one immutable account identity.
 */
export function useFunds(options: BrokerDataQueryOptions = {}) {
  const currentContext = useAccountReadContext();
  const context = options.context ?? currentContext;
  const enabled = (options.enabled ?? true) && context.enabled;
  return useQuery<Funds>({
    queryKey: queryKeys.funds.detail(context.identity.scopeKey),
    queryFn: ({ signal }) => getFunds(context, signal),
    enabled,
    staleTime: 15_000,
    refetchInterval: enabled ? 30_000 : false,
  });
}
