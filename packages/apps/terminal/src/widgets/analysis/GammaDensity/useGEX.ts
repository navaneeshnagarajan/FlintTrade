/**
 * useGEX — TanStack Query hook for the gamma-exposure decomposition.
 * Fetches from the FlintTrade backend /ft-api/api/v1/gex via POST.
 *
 * Sibling of {@link useGammaDensity}: the backend serves both from the same
 * option-chain snapshot, and the Dealer Gamma widget enables exactly one of
 * them at a time (whichever view is on screen), so the merge did not double
 * the market-hours poll.
 */

import { useQuery } from "@tanstack/react-query";
import { getGEXData } from "@/services/ftApi";
import { isMarketHours } from "@/lib/market";

export function useGEX(
  symbol: string,
  exchange: string,
  expiry: string,
  isConnected = false,
) {
  return useQuery({
    queryKey: ["gex", symbol, exchange, expiry],
    queryFn: () => getGEXData(symbol, exchange, expiry),
    // An expiry is required: without one the backend cannot resolve an
    // authoritative chain and answers with a flagged sample payload, which
    // costs a round trip to render a "Demo data" badge the widget already
    // shows. Matches useGammaDensity's precondition.
    enabled: isConnected && Boolean(symbol && exchange && expiry),
    refetchInterval: isConnected && Boolean(expiry) && isMarketHours() ? 30_000 : false,
    staleTime: 25_000,
  });
}
