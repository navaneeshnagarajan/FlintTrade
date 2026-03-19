import { useQuery } from "@tanstack/react-query";
import { getHoldings } from "@/services/api";
import type { Holding } from "@/types/api";

export function useHoldings() {
  return useQuery<Holding[]>({
    queryKey: ["holdings"],
    queryFn: getHoldings,
    refetchInterval: 60_000,
    retry: false,
  });
}
