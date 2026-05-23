import { useQuery } from "@tanstack/react-query";
import { getSyntheticFuture } from "@/services/api";
import type { SyntheticFutureData } from "@/types/api";
import { isMarketHours } from "@/lib/market";

export function useSyntheticFuture(symbol: string, exchange: string, expiry?: string) {
  return useQuery<SyntheticFutureData>({
    queryKey: ["syntheticFuture", symbol, exchange, expiry],
    queryFn: () => getSyntheticFuture(symbol, exchange, expiry),
    enabled: !!symbol && !!exchange,
    refetchInterval: () => (isMarketHours() ? 10_000 : false),
  });
}
