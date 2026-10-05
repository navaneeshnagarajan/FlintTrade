import { useQuery } from "@tanstack/react-query";
import { getOptionChain } from "@/services/api";
import { isMarketHours } from "@/lib/market";
import type { OptionChainData } from "@/types/api";
import { useMarketDataScope } from "@/hooks/useDataScope";

export function useOptionChain(symbol: string, exchange = "NFO", expiry?: string) {
  const scope = useMarketDataScope();
  return useQuery<OptionChainData>({
    queryKey: ["optionchain", scope, symbol, exchange, expiry],
    queryFn: ({ signal }) => getOptionChain(symbol, exchange, expiry, signal, scope),
    enabled: Boolean(symbol && expiry),
    refetchInterval: () => (isMarketHours() ? 30_000 : false),
  });
}
