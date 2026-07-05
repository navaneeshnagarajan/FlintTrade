/**
 * useBrokerConnected — returns true when at least one broker is connected.
 *
 * Combines two connection paths:
 *   - Gateway mode: any BrokerAccount in brokerStore with status "connected"
 *   - Legacy mode: OpenAlgo connection in connectionStore with status "connected"
 *   - Native mode: any /native/accounts entry with a live session
 *
 * Used by analysis widgets to decide whether to show live data or sample
 * data wrapped in a FeatureTeaser.
 */

import { useShallow } from "zustand/react/shallow";
import { useQuery } from "@tanstack/react-query";
import { useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { listNativeAccounts } from "@/services/ftApi.native";

export function useDirectBrokerConnected(): boolean {
  const hasGatewayAccount = useBrokerStore(
    useShallow((s) => s.accounts.some((a) => a.status === "connected")),
  );
  const nativeAccountsQuery = useQuery({
    queryKey: ["native", "accounts"],
    queryFn: listNativeAccounts,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
  const hasNativeAccount = (nativeAccountsQuery.data ?? []).some((a) => a.has_session === true);

  return hasGatewayAccount || hasNativeAccount;
}

export function useBrokerConnected(): boolean {
  const directBrokerConnected = useDirectBrokerConnected();
  const legacyStatus = useConnectionStore((s) => s.status);

  return directBrokerConnected || legacyStatus === "connected";
}
