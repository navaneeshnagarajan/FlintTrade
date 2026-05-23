/**
 * useBrokerConnected — returns true when at least one broker is connected.
 *
 * Combines two connection paths:
 *   - Gateway mode: any BrokerAccount in brokerStore with status "connected"
 *   - Legacy mode: OpenAlgo connection in connectionStore with status "connected"
 *
 * Used by analysis widgets to decide whether to show live data or sample
 * data wrapped in a FeatureTeaser.
 */

import { useShallow } from "zustand/react/shallow";
import { useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";

export function useBrokerConnected(): boolean {
  const hasGatewayAccount = useBrokerStore(
    useShallow((s) => s.accounts.some((a) => a.status === "connected")),
  );
  const legacyStatus = useConnectionStore((s) => s.status);

  return hasGatewayAccount || legacyStatus === "connected";
}
