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
import { useModeStore } from "@/stores/modeStore";

export function useDirectBrokerConnected(): boolean {
  // AppLayout owns the single auth- and mode-gated broker-account poll. This
  // selector only consumes its synchronised snapshot so Explore cannot be
  // re-enabled by a nested widget mounting another observer.
  return useBrokerStore(
    useShallow((s) => s.accounts.some((a) => a.status === "connected")),
  );
}

export function useBrokerConnected(): boolean {
  const directBrokerConnected = useDirectBrokerConnected();
  const legacyStatus = useConnectionStore((s) => s.status);
  const mode = useModeStore((s) => s.mode);

  // Explore is broker-free even during the first render after leaving Live.
  // A stale OpenAlgo status must not enable account-backed child queries.
  return mode !== "explore" && (directBrokerConnected || legacyStatus === "connected");
}
