/**
 * Runtime operator-incident signals. Probes and existing error paths write
 * here; the pure classifier in `operatorIncident` reads a snapshot.
 */

import { create } from "zustand";
import {
  classifyObservedFailure,
  type BrokerRejectSignal,
  type TransportReason,
} from "@/lib/operatorIncident";

export interface OperatorSignalSnapshot {
  localPing: "unknown" | "ok" | "transport" | "http_error";
  transportReason: TransportReason | null;
  health: "unknown" | "healthy" | "degraded" | "unhealthy";
  publicSite: "unknown" | "ok" | "unreachable";
  publicInternet: "unknown" | "ok" | "unreachable";
  nativeHttpFreeze: boolean;
  brokerRateLimited: boolean;
  brokerReject: BrokerRejectSignal | null;
  observedHostDown: boolean;
  observedBackendUnreachable: boolean;
  llmChrome: string | null;
  /** Live-facing status. Down until a heartbeat reports Ready or Degraded. Null is not Ready. */
  decisionStatus: "ready" | "degraded" | "down" | null;
  /** Sidecar status for Practice and Explore. Null is not Ready. */
  layaPracticeStatus: "ready" | "degraded" | "down" | null;
  /** True only when a qualification record covers the pin. */
  layaLiveQualified: boolean;
  /** Sidecar reason code. Null when Ready or Degraded has cleared it. */
  layaReason: string | null;
  /** Loopback port the reason refers to. The host stays 127.0.0.1. */
  layaPort: number;
  /** Bytes received while the reason is `downloading`. */
  layaDownloadBytes: number | null;
  /** Bytes expected while the reason is `downloading`. */
  layaDownloadTotal: number | null;
  /** True after a stop or start until the next ping confirms the gate. */
  layaChecking: boolean;
  /** Bumps when a place updates the chip, so an older ping cannot overwrite it. */
  layaEpoch: number;
}

const INITIAL: OperatorSignalSnapshot = {
  localPing: "unknown",
  transportReason: null,
  health: "unknown",
  publicSite: "unknown",
  publicInternet: "unknown",
  nativeHttpFreeze: false,
  brokerRateLimited: false,
  brokerReject: null,
  observedHostDown: false,
  observedBackendUnreachable: false,
  llmChrome: null,
  decisionStatus: "down",
  layaPracticeStatus: "down",
  layaLiveQualified: false,
  layaReason: null,
  layaPort: 8000,
  layaDownloadBytes: null,
  layaDownloadTotal: null,
  layaChecking: false,
  layaEpoch: 0,
};

interface OperatorSignalStore extends OperatorSignalSnapshot {
  setPing: (probe: { localPing: OperatorSignalSnapshot["localPing"]; transportReason: TransportReason | null }) => void;
  setHealth: (health: OperatorSignalSnapshot["health"]) => void;
  setPublicSite: (publicSite: OperatorSignalSnapshot["publicSite"]) => void;
  setPublicInternet: (publicInternet: OperatorSignalSnapshot["publicInternet"]) => void;
  setLlmChrome: (llmChrome: string | null) => void;
  setDecisionStatus: (decisionStatus: OperatorSignalSnapshot["decisionStatus"]) => void;
  setLayaPracticeStatus: (layaPracticeStatus: OperatorSignalSnapshot["layaPracticeStatus"]) => void;
  setLayaLiveQualified: (layaLiveQualified: boolean) => void;
  setLayaReason: (layaReason: string | null) => void;
  setLayaPort: (layaPort: number) => void;
  setLayaDownloadProgress: (layaDownloadBytes: number | null, layaDownloadTotal: number | null) => void;
  /** The order gate refused because Laya is Down. The chip must not stay Ready. */
  noteLayaDown: () => void;
  /** A stop or start is not confirmed yet. The chip says Checking, not the last label. */
  noteLayaUnconfirmed: () => void;
  /** Clear or set Checking without moving the epoch. A confirmed ping clears it. */
  setLayaChecking: (layaChecking: boolean) => void;
  clearBrokerRateLimit: () => void;
  clearBrokerFault: () => void;
  applyObserved: (
    observed: NonNullable<ReturnType<typeof classifyObservedFailure>>,
    broker: string | null,
  ) => void;
}

export const useOperatorSignalStore = create<OperatorSignalStore>((set, get) => ({
  ...INITIAL,
  setPing: (probe) => set({
    localPing: probe.localPing,
    transportReason: probe.transportReason,
    observedHostDown: probe.localPing === "ok" ? false : get().observedHostDown,
    observedBackendUnreachable: probe.localPing === "ok" ? false : get().observedBackendUnreachable,
  }),
  setHealth: (health) => set({ health }),
  setPublicSite: (publicSite) => set({ publicSite }),
  setPublicInternet: (publicInternet) => set({ publicInternet }),
  setLlmChrome: (llmChrome) => set({ llmChrome }),
  setDecisionStatus: (decisionStatus) => set({ decisionStatus }),
  setLayaPracticeStatus: (layaPracticeStatus) => set({ layaPracticeStatus }),
  setLayaLiveQualified: (layaLiveQualified) => set({ layaLiveQualified }),
  setLayaReason: (layaReason) => set({ layaReason }),
  setLayaPort: (layaPort) => set({ layaPort }),
  setLayaDownloadProgress: (layaDownloadBytes, layaDownloadTotal) => set({ layaDownloadBytes, layaDownloadTotal }),
  noteLayaDown: () => set((state) => ({
    decisionStatus: "down",
    layaPracticeStatus: "down",
    layaChecking: false,
    layaEpoch: state.layaEpoch + 1,
  })),
  noteLayaUnconfirmed: () => set((state) => ({
    layaChecking: true,
    layaEpoch: state.layaEpoch + 1,
  })),
  setLayaChecking: (layaChecking) => set({ layaChecking }),
  clearBrokerRateLimit: () => set((state) => ({
    brokerRateLimited: false,
    brokerReject: state.brokerReject
      && classifyObservedFailure({
        message: state.brokerReject.message,
        httpStatus: state.brokerReject.httpStatus,
      }, "broker")?.kind === "rate_limit"
      ? null
      : state.brokerReject,
  })),
  clearBrokerFault: () => set({
    brokerRateLimited: false,
    brokerReject: null,
  }),
  applyObserved: (observed, broker) => {
    if (observed.kind === "freeze") {
      set({ nativeHttpFreeze: true });
      return;
    }
    if (observed.kind === "rate_limit") {
      set({
        brokerRateLimited: true,
        brokerReject: { message: observed.message, httpStatus: observed.httpStatus, broker },
      });
      return;
    }
    if (observed.failureClass === "host_unhealthy") {
      set({ observedHostDown: true });
      return;
    }
    if (observed.failureClass === "backend_unreachable") {
      set({ observedBackendUnreachable: true });
      return;
    }
    set({
      brokerReject: { message: observed.message, httpStatus: observed.httpStatus, broker },
    });
  },
}));

export function resetOperatorSignals(): void {
  useOperatorSignalStore.setState(INITIAL);
}

export function clearBrokerFault(): void {
  useOperatorSignalStore.getState().clearBrokerFault();
}

export function noteObservedFailure(input: {
  message: string;
  httpStatus: number | null;
  broker?: string | null;
  provenance?: "general" | "broker" | "order";
}): void {
  const observed = classifyObservedFailure({
    message: input.message,
    httpStatus: input.httpStatus,
  }, input.provenance ?? "general");
  if (!observed) return;
  useOperatorSignalStore.getState().applyObserved(observed, input.broker ?? null);
}
