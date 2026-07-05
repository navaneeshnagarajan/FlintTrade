/**
 * useBrokerConnected — returns true when at least one broker is connected.
 *
 * Combines two connection paths:
 *   - Direct broker mode: any unified BrokerAccount in brokerStore with status "connected"
 *   - Legacy mode: OpenAlgo connection in connectionStore with status "connected"
 *
 * Used by analysis widgets to decide whether to show live data or sample
 * data wrapped in a FeatureTeaser.
 */

import { useShallow } from "zustand/react/shallow";
import { useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useBrokerAccounts } from "@/hooks/useBrokerAccounts";

export function useDirectBrokerConnected(): boolean {
  useBrokerAccounts();
  return useBrokerStore(
    useShallow((s) => s.accounts.some((a) => a.status === "connected")),
  );
}

export function useBrokerConnected(): boolean {
  const directBrokerConnected = useDirectBrokerConnected();
  const legacyStatus = useConnectionStore((s) => s.status);

  return directBrokerConnected || legacyStatus === "connected";
}
