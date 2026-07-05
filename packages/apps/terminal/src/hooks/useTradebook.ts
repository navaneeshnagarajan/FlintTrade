import { useQuery } from "@tanstack/react-query";
import { getTradebook } from "@/services/api";
import type { Trade } from "@/types/api";
import { queryKeys } from "@/services/queryKeys";

interface BrokerDataQueryOptions {
  enabled?: boolean;
}

export function useTradebook(options: BrokerDataQueryOptions = {}) {
  const enabled = options.enabled ?? true;
  return useQuery<Trade[]>({
    queryKey: queryKeys.tradebook.all,
    queryFn: getTradebook,
    enabled,
    staleTime: 15_000,
    refetchInterval: enabled ? 30_000 : false,
  });
}
