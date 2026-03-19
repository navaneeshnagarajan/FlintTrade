import { useQuery } from "@tanstack/react-query";
import { getOptionChain } from "@/services/api";
import type { OptionChainData } from "@/types/api";

export function useOptionChain(symbol: string, exchange = "NFO", expiry?: string) {
  return useQuery<OptionChainData>({
    queryKey: ["optionchain", symbol, exchange, expiry],
    queryFn: () => getOptionChain(symbol, exchange, expiry),
    enabled: !!symbol,
  });
}
