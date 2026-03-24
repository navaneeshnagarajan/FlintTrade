/**
 * useStraddlePnL — TanStack Query hook for Straddle P&L simulation data.
 * Fetches from FlintTrade backend /ft-api/api/v1/straddlepnl via POST.
 * Refetches when adjustments change (query key includes adjustments hash).
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { getStraddlePnL } from "@/services/ftApi";
import { isMarketHours } from "@/lib/market";
import type { StraddleLeg } from "@/types/api";

function hashLegs(legs: StraddleLeg[]): string {
  return JSON.stringify(legs);
}

export function useStraddlePnL(
  symbol: string,
  exchange: string,
  expiryDate: string,
  adjustments?: StraddleLeg[],
  isConnected = false,
) {
  const adjustmentsHash = useMemo(
    () => hashLegs(adjustments ?? []),
    [adjustments],
  );

  return useQuery({
    queryKey: ["straddlepnl", symbol, exchange, expiryDate, adjustmentsHash],
    queryFn: () => getStraddlePnL(symbol, exchange, expiryDate, adjustments),
    enabled: isConnected && Boolean(symbol && exchange && expiryDate),
    // P&L is static for given premiums — only refetch on param changes
    refetchInterval: isConnected && isMarketHours() ? 30_000 : false,
    staleTime: 5 * 60_000,
  });
}
