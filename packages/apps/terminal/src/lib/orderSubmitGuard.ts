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
 * when the order has them), copied from the API's `leg_outcomes`. A complete
 * order read that started at least a few seconds after the lost reply
 * settles the lock. An immediate re-read can complete before the order is
 * visible, so it does not unlock.
 */

import { z } from "zod";
import { ORDER_STATUS_UNKNOWN } from "@/lib/operatorIncident";
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

/** A complete order-book read used to settle a lost submit. */
export type OrderBookRead = {
  /** When the request left the client. */
  startedAt: number;
  /** When the complete result arrived. */
  completedAt: number;
};

/** Earliest start time, after the loss, of a read that may settle the lock. */
export const UNKNOWN_SUBMIT_SETTLE_MS = 5_000;

export interface OrderSubmitIntent {
  /** Instrument key the lock applies to, for example `NFO:NIFTY…CE`. */
  key: string;
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  quantity?: number;
}


const LEG_LABEL: Record<"entry" | "target" | "stop_loss", string> = {
  entry: "Entry",
  target: "Target",
  stop_loss: "Stop-loss",
};

/**
 * Copy shown on the unknown submit in Orders. A lone unknown entry uses the
 * approved sentence. A bracket that reports mixed legs names each one, e.g.
 * "Entry placed · Stop-loss status unknown".
 */
export function unknownSubmitSentence(record: Pick<UnknownOrderSubmit, "legs">): string {
  const named = (["entry", "target", "stop_loss"] as const).filter((leg) => {
    const outcome = record.legs[leg];
    return outcome === "confirmed" || outcome === "unknown";
  });
  const onlyUnknownEntry = named.length === 1 && named[0] === "entry" && record.legs.entry === "unknown";
  if (named.length === 0 || onlyUnknownEntry) return ORDER_STATUS_UNKNOWN;
  return named.map((leg) => {
    const label = LEG_LABEL[leg];
    return record.legs[leg] === "confirmed" ? `${label} placed` : `${label} status unknown`;
  }).join(" · ");
}

/** Short status-column chip for a mixed-leg unknown submit. The full sentence is the tooltip. */
export function unknownSubmitRowLabel(sentence: string): string {
  if (sentence.includes("Stop-loss status unknown")) return "SL unknown";
  if (sentence.includes("Target status unknown")) return "Target unknown";
  if (sentence.includes("Entry status unknown")) return "Entry unknown";
  return "Status unknown";
}

/** One-line Orders notice for pending cancels and unknown submits. */
export function ordersNoticeSummary(pendingCancels: number, unknownOrders: number): string | null {
  const parts: string[] = [];
  if (pendingCancels === 1) parts.push("1 cancellation requested");
  else if (pendingCancels > 1) parts.push(`${pendingCancels} cancellations requested`);
  if (unknownOrders === 1) parts.push("1 order status unknown");
  else if (unknownOrders > 1) parts.push(`${unknownOrders} order statuses unknown`);
  return parts.length > 0 ? parts.join(" · ") : null;
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
 * A complete order read that started at least UNKNOWN_SUBMIT_SETTLE_MS after
 * the lost reply settles the lock: it either holds the order or it does
 * not. The order book then shows the order itself, so the instrument unlocks.
 * Immediate re-reads, including a cached list treated as fresh, stay locked.
 */
export function reconcileUnknownOrderSubmits(scope: string, read: OrderBookRead): void {
  const records = readLocks(scope);
  const next = records.filter((record) => {
    const earliestStart = record.receivedAt + UNKNOWN_SUBMIT_SETTLE_MS;
    const startedLateEnough = read.startedAt >= earliestStart;
    const completedAfterLoss = read.completedAt > record.receivedAt && read.completedAt > record.listUpdatedAt;
    return !(startedLateEnough && completedAfterLoss);
  });
  if (next.length === records.length) return;
  writeLocks(scope, next);
  notify();
}
