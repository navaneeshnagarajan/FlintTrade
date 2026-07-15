/**
 * useIVSmile — TanStack Query hook for IV Smile curve data.
 * Fetches from FlintTrade backend /ft-api/api/v1/ivsmile via POST.
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { getFtIVSmile } from "@/services/ftApi";
import { isMarketHours } from "@/lib/market";

export function useIVSmile(
  symbol: string,
  exchange: string,
  expiryDates?: string[],
  isConnected = false,
) {
  const selectedExpiries = useMemo(() => (expiryDates ?? []).flatMap((value) => {
    if (typeof value !== "string") return [];
    const expiry = value.trim();
    return expiry ? [expiry] : [];
  }), [expiryDates]);
  const enabled = isConnected && Boolean(symbol && exchange) && selectedExpiries.length > 0;
  return useQuery({
    queryKey: ["ivsmile", symbol, exchange, selectedExpiries],
    queryFn: ({ signal }) => getFtIVSmile(symbol, exchange, selectedExpiries, signal),
    enabled,
    refetchInterval: enabled && isMarketHours() ? 30_000 : false,
    staleTime: 25_000,
  });
}
