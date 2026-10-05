/**
 * TanStack Query hook for fetching market depth data from the broker API.
 *
 * Returns bid/ask depth levels for a given symbol. Polls every 1 second
 * to build up the time-series the DOM Heatmap accumulates. (Written for
 * the retired DepthHeatmap widget, which merged into DOM Heatmap; the Tape
 * and DOM / Ladder surfaces share this same cache.)
 *
 * In explore mode, this hook is disabled (the widget uses synthetic data).
 */

import { useQuery } from "@tanstack/react-query";
import { getDepth } from "@/services/api";
import type { MarketDepth } from "@/types/api";
import { isDocumentHidden } from "@/lib/deskPolling";
import { useRearmPollingWhenVisible } from "@/hooks/useRearmPollingWhenVisible";
import { isMarketHours } from "@/lib/market";
import { useMarketDataScope } from "@/hooks/useDataScope";

/**
 * Fetch market depth for a symbol.
 *
 * @param symbol   - Instrument symbol (e.g. "NIFTY").
 * @param exchange - Exchange code (e.g. "NSE", "NSE_INDEX").
 * @param enabled  - Whether the query is enabled (false in explore mode).
 */
export function useDepthData(
  symbol: string,
  exchange: string,
  enabled = true,
) {
  const scope = useMarketDataScope();
  const queryKey = ["depth", scope, symbol, exchange] as const;
  useRearmPollingWhenVisible(
    queryKey,
    () => enabled && symbol.length > 0 && isMarketHours(),
  );
  return useQuery<MarketDepth>({
    queryKey,
    queryFn: ({ signal }) => getDepth(symbol, exchange, signal, scope),
    enabled: enabled && !!symbol,
    refetchInterval: () => (isDocumentHidden() || !isMarketHours() ? false : 1_000),
  });
}
