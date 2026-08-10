import { useQuery } from "@tanstack/react-query";
import { getHoldings } from "@/services/api";
import type { Holding } from "@/types/api";
import { queryKeys } from "@/services/queryKeys";
import {
  useAccountReadContext,
  type AccountReadContext,
} from "@/hooks/useAccountReadsEnabled";

interface BrokerDataQueryOptions {
  enabled?: boolean;
  context?: AccountReadContext;
}

export function useHoldings(options: BrokerDataQueryOptions = {}) {
  const currentContext = useAccountReadContext();
  const context = options.context ?? currentContext;
  const enabled = (options.enabled ?? true) && context.enabled;
  return useQuery<Holding[]>({
    queryKey: queryKeys.holdings.list(context.identity.scopeKey),
    queryFn: ({ signal }) => getHoldings(context, signal),
    enabled,
    staleTime: 30_000,
    refetchInterval: enabled ? 60_000 : false,
    retry: false,
  });
}
