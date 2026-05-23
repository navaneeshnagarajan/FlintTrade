import { useQuery } from "@tanstack/react-query";
import { getMargin } from "@/services/api";
import type { MarginData } from "@/types/api";

export function useMargin(
  symbol: string,
  exchange: string,
  qty: number,
  product: string,
  action: string,
  enabled = true,
) {
  return useQuery<MarginData>({
    queryKey: ["margin", symbol, exchange, qty, product, action],
    queryFn: () => getMargin(symbol, exchange, qty, product, action),
    enabled: enabled && !!symbol && !!exchange && qty > 0,
    staleTime: 10_000, // 10s — margin changes with market
  });
}
