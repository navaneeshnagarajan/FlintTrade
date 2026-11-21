/**
 * Pending order outcomes kept for the current tab session.
 *
 * A lost submit and an unconfirmed cancel are presentation state. The broker
 * may already hold the write, so the terminal keeps the pending line through a
 * reload until a later order read settles it. A record never authorises
 * another broker write.
 *
 * Records are keyed by operator and by a `mode:broker:account` scope, so a
 * mode or account switch hides them and sign-out clears them. A stored value
 * that fails validation is removed and treated as empty.
 */

import { z } from "zod";
import { readPersistedAuthSession } from "@/lib/homeEntry";
import { safeParse } from "@/lib/safeParse";

export const FOREVER_PENDING_CANCELS_PREFIX = "flinttrade:forever-pending-cancels";
export const ORDER_PENDING_CANCELS_PREFIX = "flinttrade:order-pending-cancels";
export const UNKNOWN_SUBMITS_PREFIX = "flinttrade:order-unknown-submits";

const ALL_PREFIXES = [
  FOREVER_PENDING_CANCELS_PREFIX,
  ORDER_PENDING_CANCELS_PREFIX,
  UNKNOWN_SUBMITS_PREFIX,
] as const;

const clearListeners = new Set<() => void>();

function sessionStorageOrNull(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/** `mode:broker:account`, matching each widget's presentation scope. */
export function pendingOrderScopeIsDurable(scope: string): boolean {
  const parts = scope.split(":");
  const [mode, broker, account] = parts;
  return (mode === "live" || mode === "practice" || mode === "explore")
    && parts.length === 3
    && Boolean(broker)
    && Boolean(account);
}

export function pendingOrderScope(identity: { mode: string; brokerType: string; accountId: string }): string {
  return `${identity.mode}:${identity.brokerType}:${identity.accountId}`;
}

function clearPrefix(prefix: string): void {
  const storage = sessionStorageOrNull();
  if (!storage) return;
  for (const key of Object.keys(storage)) {
    if (key.startsWith(`${prefix}:`)) storage.removeItem(key);
  }
}

/** Sign-out and operator change: every pending order line ends. */
export function clearPendingOrderOutcomes(): void {
  for (const prefix of ALL_PREFIXES) clearPrefix(prefix);
  for (const listener of clearListeners) listener();
}

/** In-memory holders of pending state register here to clear with storage. */
export function onPendingOrderOutcomesCleared(listener: () => void): () => void {
  clearListeners.add(listener);
  return () => clearListeners.delete(listener);
}

export interface PendingOrderStore<R> {
  /** False without a signed-in operator or a full account scope. */
  canPersist(scope: string): boolean;
  read(scope: string): R[];
  write(scope: string, records: readonly R[]): void;
  clear(): void;
}

export function createPendingOrderStore<R>(
  prefix: (typeof ALL_PREFIXES)[number],
  recordSchema: z.ZodType<R>,
): PendingOrderStore<R> {
  const listSchema = z.array(recordSchema);
  const storageKey = (scope: string): string | null => {
    if (!pendingOrderScopeIsDurable(scope)) return null;
    const username = readPersistedAuthSession()?.username;
    if (!username) return null;
    return `${prefix}:${encodeURIComponent(username)}:${encodeURIComponent(scope)}`;
  };
  return {
    canPersist(scope) {
      return storageKey(scope) !== null && sessionStorageOrNull() !== null;
    },
    read(scope) {
      const key = storageKey(scope);
      const storage = sessionStorageOrNull();
      if (!key || !storage) return [];
      const parsed = safeParse(storage.getItem(key), listSchema);
      if (!parsed) {
        if (storage.getItem(key) !== null) storage.removeItem(key);
        return [];
      }
      return parsed;
    },
    write(scope, records) {
      const key = storageKey(scope);
      const storage = sessionStorageOrNull();
      if (!key || !storage) return;
      try {
        if (records.length === 0) storage.removeItem(key);
        else storage.setItem(key, JSON.stringify(records));
      } catch {
        // Private mode or a full quota leaves the in-memory line intact.
      }
    },
    clear() {
      clearPrefix(prefix);
    },
  };
}
