/**
 * Pending Forever-order cancels for the current tab session.
 *
 * A dropped cancel is presentation state. The dispatch ledger may already
 * hold the broker write, but the Forever orders read does not return it.
 * This record lets a reloaded terminal recognise a later trigger row. It
 * does not authorise another cancel.
 */

import { z } from "zod";
import { readPersistedAuthSession } from "@/lib/homeEntry";
import { safeParse } from "@/lib/safeParse";

const STORAGE_PREFIX = "flinttrade:forever-pending-cancels";

const storedPendingCancelSchema = z.array(z.object({
  orderId: z.string().min(1),
  submittedAt: z.number().finite(),
  receivedAt: z.number().finite(),
  listUpdatedAt: z.number().finite(),
})).readonly();

export interface ForeverPendingCancel {
  scope: string;
  orderId: string;
  submittedAt: number;
  receivedAt: number;
  listUpdatedAt: number;
}

function sessionStorageOrNull(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/** Mode, broker and account, matching the widget's presentation scope. */
function foreverPendingCancelScopeIsDurable(scope: string): boolean {
  const [mode, broker, account] = scope.split(":");
  return (mode === "live" || mode === "practice" || mode === "explore")
    && scope.split(":").length === 3
    && Boolean(broker)
    && Boolean(account);
}

function foreverPendingCancelStorageKey(username: string, scope: string): string {
  return `${STORAGE_PREFIX}:${encodeURIComponent(username)}:${encodeURIComponent(scope)}`;
}

function storageKey(scope: string): string | null {
  if (!foreverPendingCancelScopeIsDurable(scope)) return null;
  const username = readPersistedAuthSession()?.username;
  if (!username) return null;
  return foreverPendingCancelStorageKey(username, scope);
}

export function readForeverPendingCancels(scope: string): ForeverPendingCancel[] {
  const key = storageKey(scope);
  const storage = sessionStorageOrNull();
  if (!key || !storage) return [];
  const parsed = safeParse(storage.getItem(key), storedPendingCancelSchema);
  if (!parsed) {
    if (storage.getItem(key) !== null) storage.removeItem(key);
    return [];
  }
  return parsed.map((record) => ({ scope, ...record }));
}

export function writeForeverPendingCancels(scope: string, pending: readonly ForeverPendingCancel[]): void {
  const key = storageKey(scope);
  const storage = sessionStorageOrNull();
  if (!key || !storage) return;
  const records = pending.filter((record) => record.scope === scope);
  try {
    if (records.length === 0) {
      storage.removeItem(key);
      return;
    }
    storage.setItem(key, JSON.stringify(records.map(({ orderId, submittedAt, receivedAt, listUpdatedAt }) => ({
      orderId, submittedAt, receivedAt, listUpdatedAt,
    }))));
  } catch {
    // Private mode or a full quota leaves the in-memory acknowledgement intact.
  }
}
