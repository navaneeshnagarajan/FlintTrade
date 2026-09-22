/**
 * Read the shared operator incident from stores the desk already keeps,
 * plus probe snapshots. Network probes live in OperatorIncidentProbes so
 * unit tests do not invent an ISP fault from jsdom.
 */

import { useMemo } from "react";
import { classifyOperatorSignals, type OperatorIncident } from "@/lib/operatorIncident";
import { isBrokerAccountMatch, useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";

export function useOperatorIncident(): OperatorIncident | null {
  const mode = useModeStore((s) => s.mode);
  const legacyStatus = useConnectionStore((s) => s.status);
  const wsFailure = useConnectionStore((s) => s.wsFailure);
  const accounts = useBrokerStore((s) => s.accounts);
  const activeAccountId = useBrokerStore((s) => s.activeAccountId);
  const localPing = useOperatorSignalStore((s) => s.localPing);
  const transportReason = useOperatorSignalStore((s) => s.transportReason);
  const health = useOperatorSignalStore((s) => s.health);
  const publicSite = useOperatorSignalStore((s) => s.publicSite);
  const nativeHttpFreeze = useOperatorSignalStore((s) => s.nativeHttpFreeze);
  const brokerRateLimited = useOperatorSignalStore((s) => s.brokerRateLimited);
  const brokerReject = useOperatorSignalStore((s) => s.brokerReject);
  const observedHostDown = useOperatorSignalStore((s) => s.observedHostDown);
  const llmChrome = useOperatorSignalStore((s) => s.llmChrome);

  return useMemo(() => {
    const directConnected = accounts.some((account) => account.status === "connected");
    const feedDisconnected = mode === "explore" || !(directConnected || legacyStatus === "connected");
    const active = accounts.find((account) => isBrokerAccountMatch(account, activeAccountId))
      ?? accounts.find((account) => account.is_primary)
      ?? null;

    return classifyOperatorSignals({
      feedDisconnected,
      localPing,
      transportReason,
      health,
      publicSite,
      nativeHttpFreeze,
      brokerRateLimited,
      brokerReject,
      observedHostDown,
      llmChrome,
      sessionClockClosed: false,
      wsFailure: wsFailure ? { kind: wsFailure.kind, reason: wsFailure.reason } : null,
      activeAccount: active
        ? {
          broker: active.broker,
          status: active.status,
          errorMessage: active.error_message,
          readSmokeOk: active.read_smoke_ok === true,
          needsRelogin: active.needs_relogin === true,
        }
        : null,
    });
  }, [
    accounts,
    activeAccountId,
    brokerRateLimited,
    brokerReject,
    health,
    legacyStatus,
    llmChrome,
    localPing,
    mode,
    nativeHttpFreeze,
    observedHostDown,
    publicSite,
    transportReason,
    wsFailure,
  ]);
}
