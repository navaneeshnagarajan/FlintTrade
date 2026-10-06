/**
 * Position-book reconcile for one contract.
 *
 * Exit copy must stay in step with ``exit_already_pending_message`` and
 * ``exit_orders_unreadable_message`` in ``flinttrade_engine.reduce_only``.
 */

export const GTT_UNSUPPORTED_MESSAGE = "Not placed. GTT orders aren't supported right now.";

export function exitAlreadyPendingMessage(contract: string): string {
  const label = contract.trim() || "this contract";
  return `Not placed. An exit for ${label} is already pending. Wait for it to fill, or cancel it and try again.`;
}

export function exitOrdersUnreadableMessage(contract: string): string {
  const label = contract.trim() || "this contract";
  return `Not placed. Broker orders for ${label} are unavailable. Reconcile them before another exit.`;
}

export function orderRefusalMessage(code: string | undefined, contract: string, fallback: string): string {
  if (code === "exit_pending") return exitAlreadyPendingMessage(contract);
  if (code === "exit_orders_unreadable") return exitOrdersUnreadableMessage(contract);
  if (code === "gtt_unsupported") return GTT_UNSUPPORTED_MESSAGE;
  return fallback;
}

/** A lost response, timeout or server failure cannot establish non-execution. */
export function orderRequestOutcomeIsUnknown(error: unknown): boolean {
  const status = error && typeof error === "object" && "status" in error ? error.status : undefined;
  return !(typeof status === "number" && status >= 400 && status < 500 && status !== 408);
}

/** Request failure without a definite refusal leaves execution unresolved. */
export function exitRequestErrorMessage(error: unknown): string {
  const details = error instanceof Error ? error.message : "";
  return orderRequestOutcomeIsUnknown(error)
    ? `Exit status unknown. An order may still execute.${details ? ` ${details}` : ""}`
    : (details || "Exit request refused.");
}

export const CANCEL_PENDING_MESSAGE = "Cancel pending. This order may still fill.";
export const EXECUTION_FIRST_WARNING = "This prioritises execution. The fill price may differ significantly, and execution isn't guaranteed.";

/** Exact known cancellation variants only; unfamiliar states remain unknown. */
export function orderStatusIsCancelPending(status: string): boolean {
  return ["CANCEL_PENDING", "CANCEL_REQUESTED", "CANCEL PENDING", "PENDING_CANCEL"]
    .includes(status.trim().toUpperCase());
}

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
  return true;
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
