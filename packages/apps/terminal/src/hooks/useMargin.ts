import { useQuery } from "@tanstack/react-query";
import { getMargin } from "@/services/api";
import { useDataScope } from "@/hooks/useDataScope";
import { queryKeys } from "@/services/queryKeys";
import type { MarginData } from "@/types/api";

export function useMargin(
  symbol: string,
  exchange: string,
  qty: number,
  product: string,
  action: string,
  enabled = true,
) {
  const scope = useDataScope();
  return useQuery<MarginData>({
    queryKey: queryKeys.margin.detail(scope, symbol, exchange, qty, product, action),
    queryFn: () => getMargin(symbol, exchange, qty, product, action),
    enabled: enabled && !!symbol && !!exchange && qty > 0,
    staleTime: 10_000, // 10s — margin changes with market
  });
}
