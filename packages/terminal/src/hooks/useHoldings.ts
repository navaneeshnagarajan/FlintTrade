import { useQuery } from "@tanstack/react-query";
import { getHoldings } from "@/services/api";
import type { Holding } from "@/types/api";
import { queryKeys } from "@/services/queryKeys";

export function useHoldings() {
  return useQuery<Holding[]>({
    queryKey: queryKeys.holdings.all,
    queryFn: getHoldings,
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: false,
  });
}
