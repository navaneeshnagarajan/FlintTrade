import { useQuery } from "@tanstack/react-query";
import { getTradebook } from "@/services/api";
import type { Trade } from "@/types/api";

export function useTradebook() {
  return useQuery<Trade[]>({
    queryKey: ["tradebook"],
    queryFn: getTradebook,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}
