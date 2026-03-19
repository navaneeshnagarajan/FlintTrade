import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { getFunds } from "@/services/api";
import { useTradingStore } from "@/stores/tradingStore";
import type { Funds } from "@/types/api";

export function useFunds() {
  const query = useQuery<Funds>({
    queryKey: ["funds"],
    queryFn: getFunds,
    refetchInterval: 30_000,
  });

  useEffect(() => {
    if (query.data) {
      useTradingStore.getState().updateFromFunds(query.data);
    }
  }, [query.data]);

  return query;
}
