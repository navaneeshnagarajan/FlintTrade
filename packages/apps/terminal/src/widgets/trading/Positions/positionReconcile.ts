/**
 * Position-book reconcile for one contract.
 *
 * ``EXIT_ALREADY_PENDING`` must stay in step with
 * ``EXIT_ALREADY_PENDING`` in ``flinttrade_engine.reduce_only``.
 */

export const EXIT_ALREADY_PENDING = "An exit for this contract is already pending.";

export const EXIT_PENDING_TAG = "Exit pending";

export const UNEXPECTED_POSITION_TAG = "Unexpected";

const CLOSED_STATUS = new Set([
  "COMPLETE",
  "COMPLETED",
  "FILLED",
  "CANCELLED",
  "CANCELED",
  "REJECTED",
  "TRADED",
  "EXPIRED",
]);

export interface ContractFields {
  symbol: string;
  exchange: string;
  product: string;
  quantity: number;
}

export interface ExitOrderFields {
  symbol: string;
  exchange: string;
  product?: string;
  action: string;
  status: string;
}

export function positionContractKey(row: {
  symbol: string;
  exchange: string;
  product?: string;
}): string {
  const product = row.product?.trim().toUpperCase() || "MIS";
  return `${row.symbol.trim().toUpperCase()}|${row.exchange.trim().toUpperCase()}|${product}`;
}

/** True unless the status is a filled, cancelled, or rejected terminal state. */
export function orderStatusIsOpen(status: string): boolean {
  const text = status.trim().toUpperCase();
  if (!text) return true;
  if (CLOSED_STATUS.has(text)) return false;
  return !text.includes("CANCEL") && !text.includes("REJECT") && !text.includes("COMPLETE");
}

/** True when one of our unfilled orders is already the exit side of this contract. */
export function contractHasOpenExit(
  position: ContractFields,
  orders: readonly ExitOrderFields[],
): boolean {
  if (position.quantity === 0) return false;
  const exit = position.quantity > 0 ? "SELL" : "BUY";
  const key = positionContractKey(position);
  return orders.some((order) => {
    if (order.action.trim().toUpperCase() !== exit) return false;
    if (positionContractKey(order) !== key) return false;
    return orderStatusIsOpen(order.status);
  });
}

export function positionFlipMessage(
  side: "long" | "short",
  quantity: number,
  symbol: string,
): string {
  return `Position changed after your broker's orders loaded. You're now ${side} ${quantity} ${symbol}. Close it if that wasn't intended.`;
}

export interface PositionFlip {
  key: string;
  symbol: string;
  quantity: number;
  side: "long" | "short";
}

/**
 * Compare the current book with the signs we last held.
 *
 * A flip is a non-zero sign that changed. A new contract, or one that went
 * flat, is not a flip and is not folded into the previous row.
 */
export function reconcilePositionSigns(
  previous: ReadonlyMap<string, 1 | -1>,
  rows: readonly ContractFields[],
): { next: Map<string, 1 | -1>; flips: PositionFlip[] } {
  const next = new Map<string, 1 | -1>();
  const flips: PositionFlip[] = [];
  for (const row of rows) {
    if (!row.symbol || row.quantity === 0) continue;
    const key = positionContractKey(row);
    const sign: 1 | -1 = row.quantity > 0 ? 1 : -1;
    next.set(key, sign);
    const prior = previous.get(key);
    if (prior != null && prior !== sign) {
      flips.push({
        key,
        symbol: row.symbol,
        quantity: Math.abs(row.quantity),
        side: sign > 0 ? "long" : "short",
      });
    }
  }
  return { next, flips };
}
