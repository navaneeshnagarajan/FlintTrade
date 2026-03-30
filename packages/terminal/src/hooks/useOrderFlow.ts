/**
 * TanStack Query hook for fetching order flow footprint data from the
 * FlintTrade backend (/ft-api/v1/orderflow).
 *
 * Returns bucketed buy/sell volume per price level, POC, delta, and totals.
 * Refreshes every 5 seconds while a symbol is active.
 */

import { useQuery } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FootprintCell {
  buy_volume: number;
  sell_volume: number;
}

export interface FootprintBucket {
  time_label: string;
  cells: Record<string, FootprintCell>;
  poc_price: number;
  total_volume: number;
  delta: number;
}

export interface OrderFlowData {
  buckets: FootprintBucket[];
  symbol: string;
  interval: number;
}

// ---------------------------------------------------------------------------
// Fetch helper
// ---------------------------------------------------------------------------

async function fetchOrderFlow(
  symbol: string,
  exchange: string,
  interval: number,
): Promise<OrderFlowData> {
  const params = new URLSearchParams({
    symbol,
    exchange,
    interval: String(interval),
  });

  const res = await fetch(`/ft-api/v1/orderflow?${params.toString()}`);

  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as {
      message?: string;
    } | null;
    throw new Error(
      body?.message ?? `Order flow request failed (${res.status})`,
    );
  }

  const json = (await res.json()) as {
    status: string;
    data: OrderFlowData;
    message?: string;
  };

  if (json.status === "error") {
    throw new Error(json.message ?? "Order flow API error");
  }

  return json.data;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Fetch order flow footprint buckets for a given symbol.
 *
 * @param symbol   - Instrument symbol (e.g. "NIFTY"). Empty string disables the query.
 * @param exchange - Exchange code (default "NSE").
 * @param interval - Bucket width in seconds (default 60).
 */
export function useOrderFlow(
  symbol: string,
  exchange = "NSE",
  interval = 60,
) {
  return useQuery<OrderFlowData>({
    queryKey: ["orderflow", symbol, exchange, interval],
    queryFn: () => fetchOrderFlow(symbol, exchange, interval),
    enabled: !!symbol,
    refetchInterval: 5_000,
  });
}
