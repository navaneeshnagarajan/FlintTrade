/**
 * TanStack Query hook for fetching order flow footprint data from the
 * FlintTrade backend (GET /ft-api/api/v1/data/orderflow via Vite proxy).
 *
 * Returns bucketed buy/sell volume per price level, POC, delta, and totals.
 * The backend responds with `is_live: true` only for fresh aggregator data.
 * `live_state` distinguishes delayed/stale retained buckets from warming or
 * unavailable states that fall back to the synthetic generator.
 *
 * Auto-refreshes every 5 seconds while the selected exchange is open and every
 * 60 seconds outside its session so the query can self-activate at open.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { isMarketHours } from "@/lib/market";
import { getSymbol } from "@/services/api";
import { getOrderFlow } from "@/services/ftApi.data";
import type { OrderFlowResponse } from "@/services/ftApi.data";

// Re-export the canonical types so existing imports from "@/hooks/useOrderFlow"
// continue to work without changes to the widget.
export type { OrderFlowResponse as OrderFlowData };
export type { OrderFlowBucket as FootprintBucket } from "@/services/ftApi.data";
export type { OrderFlowCell as FootprintCell } from "@/services/ftApi.data";

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Fetch order flow footprint buckets for a given symbol.
 *
 * @param symbol   - Instrument symbol (e.g. "NIFTY"). Empty string disables the query.
 * @param exchange - Exchange code (default "NFO").
 * @param interval - Bucket width in seconds (default 300 = 5 minutes).
 * @param bins     - Number of most-recent bins to return (default 50).
 */
export function useOrderFlow(
  symbol: string,
  exchange = "NFO",
  interval = 300,
  bins = 50,
) {
  const queryClient = useQueryClient();

  return useQuery<OrderFlowResponse>({
    queryKey: ["orderflow", symbol, exchange, interval, bins],
    queryFn: async () => {
      const metadata = await queryClient.fetchQuery({
        queryKey: ["symbol", symbol, exchange],
        queryFn: () => getSymbol(symbol, exchange),
        staleTime: 30 * 60_000,
      });
      const tickSize = Number(metadata.tick_size);
      if (!Number.isFinite(tickSize) || tickSize <= 0) {
        throw new Error(`Instrument tick size unavailable for ${symbol} on ${exchange}.`);
      }
      return getOrderFlow(symbol, exchange, bins, interval, tickSize);
    },
    enabled: !!symbol,
    // Poll every 5 s during market hours; re-check every 60 s otherwise
    // so the widget self-activates when the market opens.
    refetchInterval: () => (isMarketHours({ exchange, symbol }) ? 5_000 : 60_000),
    staleTime: 4_000,
    // Retry count is intentionally left at the TanStack Query default (3)
    // so tests can override via QueryClient defaultOptions.
  });
}
