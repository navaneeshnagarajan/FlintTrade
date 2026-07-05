import { useQuery } from "@tanstack/react-query";
import { getHoldings } from "@/services/api";
import type { Holding } from "@/types/api";
import { queryKeys } from "@/services/queryKeys";

interface BrokerDataQueryOptions {
  enabled?: boolean;
}

export function useHoldings(options: BrokerDataQueryOptions = {}) {
  const enabled = options.enabled ?? true;
  return useQuery<Holding[]>({
    queryKey: queryKeys.holdings.all,
    queryFn: getHoldings,
    enabled,
    staleTime: 30_000,
    refetchInterval: enabled ? 60_000 : false,
    retry: false,
  });
}
