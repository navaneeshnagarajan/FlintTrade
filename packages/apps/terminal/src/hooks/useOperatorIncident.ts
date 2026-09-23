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
import { useModeStore, type AppMode } from "@/stores/modeStore";
import { useOperatorSignalStore, type OperatorSignalSnapshot } from "@/stores/operatorSignalStore";
import type { BrokerAccount } from "@/types/broker";

interface IncidentSnapshot {
  mode: AppMode;
  legacyStatus: string;
  wsFailure: { kind: "auth" | "network"; reason: string } | null;
  accounts: BrokerAccount[];
  activeAccountId: string | null;
  signals: OperatorSignalSnapshot;
  sessionClockClosed: boolean;
}

function incidentFromSnapshot(snapshot: IncidentSnapshot): OperatorIncident | null {
  const directConnected = snapshot.accounts.some((account) => account.status === "connected");
  const active = snapshot.accounts.find((account) => isBrokerAccountMatch(account, snapshot.activeAccountId))
    ?? snapshot.accounts.find((account) => account.is_primary)
    ?? null;

  return classifyOperatorSignals({
    feedDisconnected: snapshot.mode === "explore" || !(directConnected || snapshot.legacyStatus === "connected"),
    localPing: snapshot.signals.localPing,
    transportReason: snapshot.signals.transportReason,
    health: snapshot.signals.health,
    publicSite: snapshot.signals.publicSite,
    publicInternet: snapshot.signals.publicInternet,
    nativeHttpFreeze: snapshot.signals.nativeHttpFreeze,
    brokerRateLimited: snapshot.signals.brokerRateLimited,
    brokerReject: snapshot.signals.brokerReject,
    observedHostDown: snapshot.signals.observedHostDown,
    observedBackendUnreachable: snapshot.signals.observedBackendUnreachable,
    llmChrome: snapshot.signals.llmChrome,
    decisionStatus: snapshot.signals.decisionStatus,
    sessionClockClosed: snapshot.sessionClockClosed,
    wsFailure: snapshot.wsFailure,
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
}

function currentSnapshot(): IncidentSnapshot {
  const signals = useOperatorSignalStore.getState();
  const wsFailure = useConnectionStore.getState().wsFailure;
  return {
    mode: useModeStore.getState().mode,
    legacyStatus: useConnectionStore.getState().status,
    wsFailure: wsFailure ? { kind: wsFailure.kind, reason: wsFailure.reason } : null,
    accounts: useBrokerStore.getState().accounts,
    activeAccountId: useBrokerStore.getState().activeAccountId,
    signals,
    sessionClockClosed: cashSessionClockClosed(),
  };
}

export function readOperatorIncident(): OperatorIncident | null {
  return incidentFromSnapshot(currentSnapshot());
}

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
  const publicInternet = useOperatorSignalStore((s) => s.publicInternet);
  const nativeHttpFreeze = useOperatorSignalStore((s) => s.nativeHttpFreeze);
  const brokerRateLimited = useOperatorSignalStore((s) => s.brokerRateLimited);
  const brokerReject = useOperatorSignalStore((s) => s.brokerReject);
  const observedHostDown = useOperatorSignalStore((s) => s.observedHostDown);
  const observedBackendUnreachable = useOperatorSignalStore((s) => s.observedBackendUnreachable);
  const llmChrome = useOperatorSignalStore((s) => s.llmChrome);
  const decisionStatus = useOperatorSignalStore((s) => s.decisionStatus);
  const sessionClockClosed = cashSessionClockClosed();

  return useMemo(() => incidentFromSnapshot({
    mode,
    legacyStatus,
    wsFailure: wsFailure ? { kind: wsFailure.kind, reason: wsFailure.reason } : null,
    accounts,
    activeAccountId,
    signals: {
      localPing,
      transportReason,
      health,
      publicSite,
      publicInternet,
      nativeHttpFreeze,
      brokerRateLimited,
      brokerReject,
      observedHostDown,
      observedBackendUnreachable,
      llmChrome,
      decisionStatus,
    },
    sessionClockClosed,
  }), [
    accounts,
    activeAccountId,
    brokerRateLimited,
    brokerReject,
    decisionStatus,
    health,
    legacyStatus,
    llmChrome,
    localPing,
    mode,
    nativeHttpFreeze,
    observedBackendUnreachable,
    observedHostDown,
    publicInternet,
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
