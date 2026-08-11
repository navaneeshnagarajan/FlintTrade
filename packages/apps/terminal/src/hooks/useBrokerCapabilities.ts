/**
 * useBrokerCapabilities — fetches broker metadata for OpenAlgo or native mode.
 *
 * Returns supported exchanges, broker type (equity/crypto/commodity/multi),
 * and feature flags (market_protection, leverage, bracket_orders, etc.).
 *
 * Cached for 5 minutes — broker capabilities rarely change within a session.
 */

import { useQuery } from "@tanstack/react-query";
import { connectionScopeFingerprint } from "@/hooks/useDataScope";
import { getBrokerCapabilities } from "@/services/api";
import { findBrokerAccountMatch, useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";
import type { BrokerCapabilities } from "@/types/api";

export function useBrokerCapabilities(enabled = true) {
  const mode = useModeStore((state) => state.mode);
  const host = useConnectionStore((state) => state.host);
  const apiKey = useConnectionStore((state) => state.apiKey);
  const hasOpenAlgoKey = apiKey.trim().length > 0;
  const accounts = useBrokerStore((state) => state.accounts);
  const activeAccountId = useBrokerStore((state) => state.activeAccountId);
  const active = findBrokerAccountMatch(accounts, activeAccountId);
  const selected = active ?? accounts.find((account) => account.is_primary) ?? accounts[0];
  const nativeBroker = selected?.source === "native" ? selected.broker : undefined;
  const sourceScope = mode === "explore"
    ? "explore"
    : hasOpenAlgoKey
      ? `openalgo:${connectionScopeFingerprint(host, apiKey)}`
      : nativeBroker
        ? `native:${nativeBroker}`
        : "native:unconfigured";

  return useQuery<BrokerCapabilities>({
    // Capability data must not survive an authority change under the five
    // minute freshness window. Deliberately key only on non-secret identity.
    queryKey: ["broker", "capabilities", mode, sourceScope],
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
