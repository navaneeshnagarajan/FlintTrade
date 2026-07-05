import { useQuery } from "@tanstack/react-query";
import { getOrderbook } from "@/services/api";
import type { Order } from "@/types/api";
import { isMarketHours } from "@/lib/market";
import { queryKeys } from "@/services/queryKeys";

interface BrokerDataQueryOptions {
  enabled?: boolean;
}

export function useOrders(options: BrokerDataQueryOptions = {}) {
  const enabled = options.enabled ?? true;
  return useQuery<Order[]>({
    queryKey: queryKeys.orders.all,
    queryFn: getOrderbook,
    enabled,
    staleTime: 5_000,
    refetchInterval: () => (enabled && isMarketHours() ? 10_000 : false),
  });
}
