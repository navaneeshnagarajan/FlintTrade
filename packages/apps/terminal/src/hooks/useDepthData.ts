/**
 * TanStack Query hook for fetching market depth data from the OpenAlgo API.
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
import { isMarketHours } from "@/lib/market";

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
  return useQuery<MarketDepth>({
    queryKey: ["depth", symbol, exchange],
    queryFn: () => getDepth(symbol, exchange),
    enabled: enabled && !!symbol,
    refetchInterval: () => (isMarketHours() ? 1_000 : false),
    // Keep previous data while refetching to avoid flicker
    placeholderData: (prev) => prev,
  });
}
