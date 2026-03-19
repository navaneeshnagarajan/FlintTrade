import { useQuery } from "@tanstack/react-query";
import { getFunds } from "@/services/api";
import { useTradingStore } from "@/stores/tradingStore";
import type { Funds } from "@/types/api";

export function useFunds() {
  return useQuery<Funds>({
    queryKey: ["funds"],
    queryFn: getFunds,
    refetchInterval: 30_000,
    select: (data) => {
      useTradingStore.getState().updateFromFunds(data);
      return data;
    },
  });
}
