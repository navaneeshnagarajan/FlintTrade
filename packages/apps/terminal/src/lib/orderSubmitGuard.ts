/**
 * One place request per intent, and a lock after a lost submit.
 *
 * Fast paths (option-chain Buy/Sell, Scalper one-click and hotkeys) route
 * their place call through `submitOrderOnce`. A second click or hotkey press
 * while the first request is in flight sends nothing. When the reply is lost
 * (dropped connection, timeout, or a server error after the broker may have
 * accepted it), the instrument stays locked and shows the unknown sentence
 * until a newer complete order read settles it, either with the order or
 * without it. Nothing here resubmits.
 *
 * Locks live in the shared pending-order store, so they survive a reload,
 * are hidden by a mode or account switch, and clear on sign-out.
 */

import { z } from "zod";
import { presentSubmitError } from "@/lib/orderOutcome";
import {
  createPendingOrderStore,
  onPendingOrderOutcomesCleared,
  UNKNOWN_SUBMITS_PREFIX,
} from "@/lib/pendingOrderStore";

const unknownSubmitSchema = z.object({
  key: z.string().min(1),
  symbol: z.string().min(1),
  exchange: z.string(),
  action: z.enum(["BUY", "SELL"]),
  quantity: z.number().finite().optional(),
  receivedAt: z.number().finite(),
  listUpdatedAt: z.number().finite(),
});

export type UnknownOrderSubmit = z.infer<typeof unknownSubmitSchema>;

export interface OrderSubmitIntent {
  /** Instrument key the lock applies to, for example `NFO:NIFTY…CE`. */
  key: string;
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  quantity?: number;
}

export type SubmitOnceResult<T> = { sent: false } | { sent: true; value: T };

const store = createPendingOrderStore(UNKNOWN_SUBMITS_PREFIX, unknownSubmitSchema);
/** Locks that cannot be stored for the session still hold for this page. */
const unstored = new Map<string, UnknownOrderSubmit[]>();
const inFlight = new Set<string>();
const listeners = new Set<() => void>();
let version = 0;

function notify(): void {
  version += 1;
  for (const listener of listeners) listener();
}

onPendingOrderOutcomesCleared(() => {
  unstored.clear();
  notify();
});

function readLocks(scope: string): UnknownOrderSubmit[] {
  return store.canPersist(scope) ? store.read(scope) : unstored.get(scope) ?? [];
}

function writeLocks(scope: string, records: UnknownOrderSubmit[]): void {
  if (store.canPersist(scope)) store.write(scope, records);
  else if (records.length > 0) unstored.set(scope, records);
  else unstored.delete(scope);
}

export function subscribeOrderSubmitGuard(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function orderSubmitGuardVersion(): number {
  return version;
}

export function readUnknownOrderSubmits(scope: string): UnknownOrderSubmit[] {
  return readLocks(scope);
}

export function orderSubmitInFlight(scope: string, key: string): boolean {
  return inFlight.has(`${scope}|${key}`);
}

export function orderSubmitLocked(scope: string, key: string): boolean {
  return orderSubmitInFlight(scope, key) || readLocks(scope).some((record) => record.key === key);
}

/**
 * Send at most one place request for this instrument at a time. Returns
 * `{ sent: false }` without calling `send` while a request is in flight or
 * the outcome of an earlier one is unknown. Errors are rethrown for the
 * caller's own message.
 */
export async function submitOrderOnce<T>(
  scope: string,
  intent: OrderSubmitIntent,
  send: () => Promise<T>,
  listUpdatedAt = 0,
): Promise<SubmitOnceResult<T>> {
  if (orderSubmitLocked(scope, intent.key)) return { sent: false };
  const flightKey = `${scope}|${intent.key}`;
  inFlight.add(flightKey);
  notify();
  try {
    return { sent: true, value: await send() };
  } catch (error) {
    if (presentSubmitError(error).kind === "unknown") {
      writeLocks(scope, [
        ...readLocks(scope).filter((record) => record.key !== intent.key),
        { ...intent, receivedAt: Date.now(), listUpdatedAt },
      ]);
    }
    throw error;
  } finally {
    inFlight.delete(flightKey);
    notify();
  }
}

/**
 * A complete order read newer than the lost reply settles the lock: it
 * either holds the order or it does not. The order book then shows the
 * order itself, so the instrument unlocks.
 */
export function reconcileUnknownOrderSubmits(scope: string, dataUpdatedAt: number): void {
  const records = readLocks(scope);
  const next = records.filter((record) => !(dataUpdatedAt > record.receivedAt && dataUpdatedAt > record.listUpdatedAt));
  if (next.length === records.length) return;
  writeLocks(scope, next);
  notify();
}
