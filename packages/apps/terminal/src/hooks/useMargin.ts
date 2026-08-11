import { useQuery } from "@tanstack/react-query";
import { getMargin } from "@/services/api";
import { useAccountReadContext } from "@/hooks/useAccountReadsEnabled";
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
  const context = useAccountReadContext();
  return useQuery<MarginData>({
    queryKey: queryKeys.margin.detail(
      context.identity.scopeKey,
      symbol,
      exchange,
      qty,
      product,
      action,
    ),
    queryFn: ({ signal }) => getMargin(context, symbol, exchange, qty, product, action, signal),
    enabled: enabled && context.enabled && !!symbol && !!exchange && qty > 0,
    staleTime: 10_000, // 10s — margin changes with market
  });
}
