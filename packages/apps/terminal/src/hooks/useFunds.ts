import { useQuery } from "@tanstack/react-query";
import { getFunds } from "@/services/api";
import type { Funds } from "@/types/api";
import { queryKeys } from "@/services/queryKeys";
import { useDataScope } from "@/hooks/useDataScope";

interface BrokerDataQueryOptions {
  enabled?: boolean;
}

/**
 * Pure TanStack Query hook for the Funds REST endpoint.
 *
 * Does not write into any Zustand store — that mirror is maintained by
 * `useTradingStoreSync` at the app root so there is exactly one write
 * point.
 */
export function useFunds(options: BrokerDataQueryOptions = {}) {
  const enabled = options.enabled ?? true;
  const scope = useDataScope();
  return useQuery<Funds>({
    queryKey: queryKeys.funds.detail(scope),
    queryFn: getFunds,
    enabled,
    staleTime: 15_000,
    refetchInterval: enabled ? 30_000 : false,
  });
}
