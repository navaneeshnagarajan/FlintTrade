/**
 * TanStack Query hook for fetching order flow footprint data from the
 * FlintTrade backend (GET /ft-api/api/v1/data/orderflow via Vite proxy).
 *
 * Returns bucketed buy/sell volume per price level, POC, delta, and totals.
 * The backend responds with `is_live: true` when the live
 * OrderFlowAggregatorV2 has data; `is_live: false` when falling back to
 * the synthetic generator.
 *
 * Auto-refreshes every 5 seconds while the market is open (weekdays 09:15–15:30
 * IST). Outside market hours the query still succeeds but does not poll.
 */

import { useQuery } from "@tanstack/react-query";
import { getOrderFlow } from "@/services/ftApi.data";
import type { OrderFlowResponse } from "@/services/ftApi.data";

// Re-export the canonical types so existing imports from "@/hooks/useOrderFlow"
// continue to work without changes to the widget.
export type { OrderFlowResponse as OrderFlowData };
export type { OrderFlowBucket as FootprintBucket } from "@/services/ftApi.data";
export type { OrderFlowCell as FootprintCell } from "@/services/ftApi.data";

// ---------------------------------------------------------------------------
// Market hours helper (IST)
// ---------------------------------------------------------------------------

/**
 * Returns true if the current IST time is within NSE/NFO trading hours
 * (weekdays 09:15–15:30).  Used to decide the polling interval.
 */
function isMarketOpen(): boolean {
  // Get current IST time
  const now = new Date();
  const ist = new Date(
    now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }),
  );

  const day = ist.getDay(); // 0 = Sunday, 6 = Saturday
  if (day === 0 || day === 6) return false;

  const h = ist.getHours();
  const m = ist.getMinutes();
  const minutesSinceMidnight = h * 60 + m;

  const OPEN = 9 * 60 + 15;  // 09:15
  const CLOSE = 15 * 60 + 30; // 15:30

  return minutesSinceMidnight >= OPEN && minutesSinceMidnight < CLOSE;
}

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
  return useQuery<OrderFlowResponse>({
    queryKey: ["orderflow", symbol, exchange, interval, bins],
    queryFn: () => getOrderFlow(symbol, exchange, bins, interval),
    enabled: !!symbol,
    // Poll every 5 s during market hours; re-check every 60 s otherwise
    // so the widget self-activates when the market opens.
    refetchInterval: isMarketOpen() ? 5_000 : 60_000,
    staleTime: 4_000,
    // Retry count is intentionally left at the TanStack Query default (3)
    // so tests can override via QueryClient defaultOptions.
  });
}
