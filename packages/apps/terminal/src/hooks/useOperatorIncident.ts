/**
 * Read the shared operator incident from stores the desk already keeps,
 * plus probe snapshots. Network probes live in OperatorIncidentProbes so
 * unit tests do not invent an ISP fault from jsdom.
 */

import { useMemo } from "react";
import { classifyOperatorSignals, type OperatorIncident } from "@/lib/operatorIncident";
import { resolveNseCashSession } from "@/lib/nseSession";
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
  const observedBackendUnreachable = useOperatorSignalStore((s) => s.observedBackendUnreachable);
  const llmChrome = useOperatorSignalStore((s) => s.llmChrome);
  const sessionClockClosed = cashSessionClockClosed();

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
      observedBackendUnreachable,
      llmChrome,
      sessionClockClosed,
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
    observedBackendUnreachable,
    observedHostDown,
    publicSite,
    sessionClockClosed,
    transportReason,
    wsFailure,
  ]);
}

/** CAS / cash clock is read and ignored. Closed or CAS is not an exchange halt. */
function cashSessionClockClosed(now: Date = new Date()): boolean {
  const phase = resolveNseCashSession(now).phase;
  return phase === "closed" || phase === "cas";
}
