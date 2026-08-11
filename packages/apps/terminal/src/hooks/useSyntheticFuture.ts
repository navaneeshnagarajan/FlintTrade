import { useQuery } from "@tanstack/react-query";
import { getSyntheticFuture } from "@/services/api";
import type { SyntheticFutureData } from "@/types/api";
import { isMarketHours } from "@/lib/market";
import { useMarketDataScope } from "@/hooks/useDataScope";

export function useSyntheticFuture(symbol: string, exchange: string, expiry?: string) {
  const dataScope = useMarketDataScope();
  return useQuery<SyntheticFutureData>({
    queryKey: ["syntheticFuture", dataScope, symbol, exchange, expiry],
    queryFn: ({ signal }) => getSyntheticFuture(symbol, exchange, expiry, signal, dataScope),
    enabled: dataScope !== "explore:mock" && !!symbol && !!exchange,
    refetchInterval: () => (isMarketHours() ? 10_000 : false),
  });
}
