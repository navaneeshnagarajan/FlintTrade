import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { getPositionbook } from "@/services/api";
import { useTradingStore } from "@/stores/tradingStore";
import type { Position } from "@/types/api";
import { isMarketHours } from "@/lib/market";

export function usePositions() {
  const query = useQuery<Position[]>({
    queryKey: ["positions"],
    queryFn: getPositionbook,
    staleTime: 3_000,
    refetchInterval: () => (isMarketHours() ? 5_000 : 60_000),
  });

  useEffect(() => {
    if (query.data) {
      useTradingStore.getState().updateFromPositions(query.data);
    }
  }, [query.data]);

  return query;
}
