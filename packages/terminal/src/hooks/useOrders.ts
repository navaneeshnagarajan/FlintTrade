import { useQuery } from "@tanstack/react-query";
import { getOrderbook } from "@/services/api";
import type { Order } from "@/types/api";
import { isMarketHours } from "@/lib/market";
import { queryKeys } from "@/services/queryKeys";

export function useOrders() {
  return useQuery<Order[]>({
    queryKey: queryKeys.orders.all,
    queryFn: getOrderbook,
    staleTime: 5_000,
    refetchInterval: () => (isMarketHours() ? 10_000 : false),
  });
}
