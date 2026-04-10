import { useQuery } from "@tanstack/react-query";
import { getTradebook } from "@/services/api";
import type { Trade } from "@/types/api";
import { queryKeys } from "@/services/queryKeys";

export function useTradebook() {
  return useQuery<Trade[]>({
    queryKey: queryKeys.tradebook.all,
    queryFn: getTradebook,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}
