import { useSyncExternalStore } from "react";

let inFlight = false;
const listeners = new Set<() => void>();

function setInFlight(next: boolean): void {
  if (inFlight === next) return;
  inFlight = next;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** True while any cancel-all request, from a hotkey or a button, has no reply. */
export function isCancelAllInFlight(): boolean {
  return inFlight;
}

export function useCancelAllInFlight(): boolean {
  return useSyncExternalStore(subscribe, isCancelAllInFlight, () => false);
}

/**
 * Start a cancel-all request unless one is already pending. Returns null when
 * one is, and sends nothing. The flag releases on success, failure or a throw.
 */
export function sendCancelAllOnce<T>(send: () => Promise<T>): Promise<T> | null {
  if (inFlight) return null;
  setInFlight(true);
  let request: Promise<T>;
  try {
    request = send();
  } catch (error) {
    setInFlight(false);
    return Promise.reject(error);
  }
  return request.finally(() => setInFlight(false));
}
