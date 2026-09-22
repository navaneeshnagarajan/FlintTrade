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
};

interface OperatorSignalStore extends OperatorSignalSnapshot {
  setPing: (probe: { localPing: OperatorSignalSnapshot["localPing"]; transportReason: TransportReason | null }) => void;
  setHealth: (health: OperatorSignalSnapshot["health"]) => void;
  setPublicSite: (publicSite: OperatorSignalSnapshot["publicSite"]) => void;
  setPublicInternet: (publicInternet: OperatorSignalSnapshot["publicInternet"]) => void;
  setLlmChrome: (llmChrome: string | null) => void;
  clearBrokerRateLimit: () => void;
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
  clearBrokerRateLimit: () => set((state) => ({
    brokerRateLimited: false,
    brokerReject: state.brokerReject
      && classifyObservedFailure({
        message: state.brokerReject.message,
        httpStatus: state.brokerReject.httpStatus,
      })?.kind === "rate_limit"
      ? null
      : state.brokerReject,
  })),
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

export function noteObservedFailure(input: {
  message: string;
  httpStatus: number | null;
  broker?: string | null;
}): void {
  const observed = classifyObservedFailure({
    message: input.message,
    httpStatus: input.httpStatus,
  });
  if (!observed) return;
  useOperatorSignalStore.getState().applyObserved(observed, input.broker ?? null);
}
