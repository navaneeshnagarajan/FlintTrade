/**
 * "Stop-loss triggered · not filled".
 *
 * A stop-limit order whose trigger was hit but whose limit has not filled is
 * the one state where the position is no longer protected even though a
 * stop-loss exists. It shows in the reserved status slot on the Orders row and
 * the Positions chip, never only in a toast. "Exit now" opens a limit ticket
 * at the best price for the full open quantity; nothing is resent on its own
 * and nothing goes at market. The state clears when the stop or the exit fills.
 */

export const STOP_LOSS_NOT_FILLED = "Stop-loss triggered · not filled";
export const EXIT_NOW = "Exit now";

type Loose = Record<string, unknown>;

function text(row: Loose, ...keys: string[]): string {
  for (const key of keys) {
    const value = row[key];
    if (typeof value === "string" && value.trim() !== "") return value.trim();
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
  }
  return "";
}

function number(row: Loose, ...keys: string[]): number {
  const parsed = Number(text(row, ...keys));
  return Number.isFinite(parsed) ? parsed : 0;
}

function token(value: string): string {
  return value.toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_|_$/g, "");
}

const STOP_LIMIT_TYPES = new Set(["SL", "SL_L", "SL_LIMIT", "STOP_LIMIT", "STOP_LOSS", "STOPLOSS_LIMIT"]);
const DONE = new Set(["COMPLETE", "COMPLETED", "FILLED", "TRADED", "CANCELLED", "CANCELED", "REJECTED", "EXPIRED", "DELETED"]);

/** True for a stop-limit order whose trigger was hit and which has not filled. */
export function isStopLossTriggeredNotFilled(order: object): boolean {
  const row = order as Loose;
  const type = token(text(row, "orderType", "pricetype", "price_type", "order_type"));
  if (!STOP_LIMIT_TYPES.has(type)) return false;
  const status = token(text(row, "status", "order_status", "orderStatus"));
  if (DONE.has(status)) return false;
  const flagged = row.stop_triggered === true || row.stopTriggered === true;
  if (!flagged && status !== "TRIGGERED") return false;
  const quantity = number(row, "quantity", "qty");
  const filled = number(row, "filled_quantity", "filledQuantity", "filled_qty", "filledQty");
  return quantity <= 0 || filled < quantity;
}

function contractKey(row: Loose): string {
  return `${text(row, "exchange").toUpperCase()}:${text(row, "symbol", "tradingsymbol").toUpperCase()}`;
}

/** Contract keys (``EXCHANGE:SYMBOL``) with a triggered stop that has not filled. */
export function stopLossNotFilledKeys(orders: readonly object[]): Set<string> {
  const keys = new Set<string>();
  for (const order of orders) {
    if (isStopLossTriggeredNotFilled(order)) keys.add(contractKey(order as Loose));
  }
  return keys;
}

export function contractKeyOf(row: { symbol?: string; exchange?: string }): string {
  return contractKey(row as Loose);
}

export interface ExitTicket {
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  orderType: "LIMIT";
  qty: number;
  product?: string;
  price?: number;
  /** The ticket may only reduce the position; the pad caps its quantity at ``openQuantity``. */
  exitOnly: true;
  openQuantity: number;
}

/**
 * The ticket "Exit now" opens: opposite side, full open quantity, a limit at
 * the best price (bid to sell, ask to buy, else the last price). Without any
 * price the ticket opens empty for the user to fill.
 */
export function exitNowTicket(
  position: { symbol: string; exchange: string; quantity: number; product?: string },
  quote: { bid?: number | null; ask?: number | null; ltp?: number | null } | null | undefined,
): ExitTicket | null {
  if (!Number.isFinite(position.quantity) || position.quantity === 0) return null;
  const action = position.quantity > 0 ? "SELL" : "BUY";
  const side = action === "SELL" ? quote?.bid : quote?.ask;
  const best = [side, quote?.ltp].find((value) => typeof value === "number" && Number.isFinite(value) && value > 0);
  return {
    symbol: position.symbol,
    exchange: position.exchange,
    action,
    orderType: "LIMIT",
    qty: Math.abs(position.quantity),
    exitOnly: true,
    openQuantity: Math.abs(position.quantity),
    ...(position.product ? { product: position.product } : {}),
    ...(best != null ? { price: Math.round(best * 20) / 20 } : {}),
  };
}

/** Open the order ticket for an exit. The user still presses Place. */
export function openExitTicket(ticket: ExitTicket): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent("flinttrade:addWidget", {
    detail: { widgetId: "orderpad", props: { ...ticket } },
  }));
}
