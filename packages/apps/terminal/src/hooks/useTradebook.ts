import { useQuery } from "@tanstack/react-query";
import { getTradebook } from "@/services/api";
import type { Trade } from "@/types/api";
import { queryKeys } from "@/services/queryKeys";
import {
  useAccountReadContext,
  type AccountReadContext,
} from "@/hooks/useAccountReadsEnabled";

interface BrokerDataQueryOptions {
  enabled?: boolean;
  context?: AccountReadContext;
}

export function useTradebook(options: BrokerDataQueryOptions = {}) {
  const currentContext = useAccountReadContext();
  const context = options.context ?? currentContext;
  const enabled = (options.enabled ?? true) && context.enabled;
  return useQuery<Trade[]>({
    queryKey: queryKeys.tradebook.list(context.identity.scopeKey),
    queryFn: ({ signal }) => getTradebook(context, signal),
    enabled,
    staleTime: 15_000,
    refetchInterval: enabled ? 30_000 : false,
  });
}
