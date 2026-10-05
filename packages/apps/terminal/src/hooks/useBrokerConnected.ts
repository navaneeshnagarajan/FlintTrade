/** Native broker readiness for account-backed widget reads. */

import { useShallow } from "zustand/react/shallow";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";

export function useDirectBrokerConnected(): boolean {
  // AppLayout owns the single auth- and mode-gated broker-account poll. This
  // selector only consumes its synchronised snapshot so Explore cannot be
  // re-enabled by a nested widget mounting another observer.
  return useBrokerStore(
    useShallow((s) => s.accounts.some((a) => a.source === "native" && a.status === "connected")),
  );
}

export function useBrokerConnected(): boolean {
  const directBrokerConnected = useDirectBrokerConnected();
  const mode = useModeStore((s) => s.mode);

  // Explore is broker-free even during the first render after leaving Live.
  // A stale transport status must not enable account-backed child queries.
  return mode !== "explore" && directBrokerConnected;
}
