/**
 * useBrokerCapabilities — fetches broker metadata from OpenAlgo 2.0.0.2.
 *
 * Returns supported exchanges, broker type (equity/crypto/commodity/multi),
 * and feature flags (market_protection, leverage, bracket_orders, etc.).
 *
 * Cached for 5 minutes — broker capabilities rarely change within a session.
 */

import { useQuery } from "@tanstack/react-query";
import { getBrokerCapabilities } from "@/services/api";
import type { BrokerCapabilities } from "@/types/api";

export function useBrokerCapabilities(enabled = true) {
  return useQuery<BrokerCapabilities>({
    queryKey: ["broker", "capabilities"],
    queryFn: getBrokerCapabilities,
    enabled,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: 1,
  });
}

/** Helper: returns true when the connected broker is crypto-only. */
export function useIsCryptoBroker(enabled = true): boolean {
  const { data } = useBrokerCapabilities(enabled);
  return data?.broker_type === "crypto";
}
