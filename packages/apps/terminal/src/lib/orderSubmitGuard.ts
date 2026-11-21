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
 *
 * Each record carries one outcome per leg (entry, and target and stop_loss
 * when the order has them), copied from the API's `leg_outcomes`. A newer
 * complete order read settles the lock.
 */

import { z } from "zod";
import { presentSubmitError } from "@/lib/orderOutcome";
import {
  createPendingOrderStore,
  onPendingOrderOutcomesCleared,
  UNKNOWN_SUBMITS_PREFIX,
} from "@/lib/pendingOrderStore";

const legOutcomeSchema = z.enum(["unknown", "confirmed", "absent"]);

const legOutcomesSchema = z.object({
  entry: legOutcomeSchema,
  target: legOutcomeSchema.optional(),
  stop_loss: legOutcomeSchema.optional(),
}).strict();

type LegOutcomes = z.infer<typeof legOutcomesSchema>;

const unknownSubmitSchema = z.object({
  key: z.string().min(1),
  symbol: z.string().min(1),
  exchange: z.string(),
  action: z.enum(["BUY", "SELL"]),
  quantity: z.number().finite().optional(),
  receivedAt: z.number().finite(),
  listUpdatedAt: z.number().finite(),
  legs: legOutcomesSchema,
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

/** Lock key for one instrument. Every ticket for the same contract shares it. */
export function instrumentOrderKey(exchange: string, symbol: string): string {
  return `${exchange}:${symbol}`;
}

/** A dropped, timed-out, or server-failed reply: the broker may hold the order. */
export function submitReplyWasLost(error: unknown): boolean {
  return presentSubmitError(error).kind === "unknown";
}

function hasUnknownLeg(record: UnknownOrderSubmit): boolean {
  return Object.values(record.legs).includes("unknown");
}

/**
 * The legs a lost reply reports, such as a Bracket whose entry is confirmed
 * and whose exit is unknown. Without a valid report that names an unknown
 * leg, the entry leg is unknown.
 */
function lostLegOutcomes(error: unknown): LegOutcomes {
  const body = error && typeof error === "object" && "body" in error ? error.body : undefined;
  const reported = body && typeof body === "object" && "leg_outcomes" in body
    ? legOutcomesSchema.safeParse(body.leg_outcomes)
    : null;
  return reported?.success && Object.values(reported.data).includes("unknown")
    ? reported.data
    : { entry: "unknown" };
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
  return orderSubmitInFlight(scope, key) || readLocks(scope).some((record) => record.key === key && hasUnknownLeg(record));
}

/**
 * Send at most one place request for this instrument at a time. Returns
 * `{ sent: false }` without calling `send` while a request is in flight or
 * the outcome of an earlier one is unknown. Errors are rethrown for the
 * caller's own message. `isLost` must match the caller's own unknown copy.
 */
export async function submitOrderOnce<T>(
  scope: string,
  intent: OrderSubmitIntent,
  send: () => Promise<T>,
  listUpdatedAt = 0,
  isLost: (error: unknown) => boolean = submitReplyWasLost,
): Promise<SubmitOnceResult<T>> {
  if (orderSubmitLocked(scope, intent.key)) return { sent: false };
  const flightKey = `${scope}|${intent.key}`;
  inFlight.add(flightKey);
  notify();
  try {
    return { sent: true, value: await send() };
  } catch (error) {
    if (isLost(error)) {
      writeLocks(scope, [
        ...readLocks(scope).filter((record) => record.key !== intent.key),
        { ...intent, receivedAt: Date.now(), listUpdatedAt, legs: lostLegOutcomes(error) },
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
