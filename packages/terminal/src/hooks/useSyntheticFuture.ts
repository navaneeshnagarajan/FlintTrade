import { useQuery } from "@tanstack/react-query";
import { getSyntheticFuture } from "@/services/api";
import type { SyntheticFutureData } from "@/types/api";

function isMarketHours(): boolean {
  const ist = new Date(
    new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }),
  );
  const mins = ist.getHours() * 60 + ist.getMinutes();
  const day = ist.getDay();
  if (day === 0 || day === 6) return false;
  return mins >= 555 && mins <= 930;
}

export function useSyntheticFuture(symbol: string, exchange: string, expiry?: string) {
  return useQuery<SyntheticFutureData>({
    queryKey: ["syntheticFuture", symbol, exchange, expiry],
    queryFn: () => getSyntheticFuture(symbol, exchange, expiry),
    enabled: !!symbol && !!exchange,
    refetchInterval: isMarketHours() ? 10_000 : false,
  });
}
