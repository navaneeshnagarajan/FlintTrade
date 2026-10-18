/**
 * orderGuards — the single source of truth for client-side pre-trade guards.
 *
 * Every order-entry surface (Order Pad, Quick Trade, Scalper, Order Ladder,
 * Orders) previously carried its own copy of these rules. The copies drifted:
 * two surfaces could send a ₹0 LIMIT order that a third refused, one surface
 * had no explore-mode block, another validated no lot size at all, and the
 * derivative-exchange list disagreed between files.
 *
 * These guards are a client-side *courtesy* layer only. They exist so the
 * operator gets an immediate, specific refusal instead of a broker rejection.
 * The authoritative gate is always server-side: SafetySystem L1-L5 →
 * gate_order → BrokerRouter → adapter. Nothing here may be treated as the
 * reason an order is safe.
 *
 * Every guard fails CLOSED: when an input cannot be verified the guard refuses
 * rather than guessing. Guards return a human-readable refusal string, or null
 * when the check passes, so each surface keeps its own presentation (toast,
 * inline field error, status line).
 */

import type { AppMode } from "@/stores/modeStore";

// ---------------------------------------------------------------------------
// Exchange classification
// ---------------------------------------------------------------------------

/**
 * Derivative exchanges where quantity MUST be a positive multiple of the
 * instrument's lot size.
 *
 * NFO = NSE F&O, BFO = BSE F&O, MCX = commodities, CDS = NSE currency,
 * BCD = BSE currency. A wrong F&O quantity is a broker rejection at best and
 * an unintended position size at worst, so this list is the union of every
 * per-widget copy that preceded it (Quick Trade carried BCD; Order Pad did
 * not — the union keeps BCD, because a currency-derivative order sized in
 * shares is exactly the mistake these guards exist to prevent).
 */
export const DERIVATIVE_EXCHANGES: ReadonlySet<string> = new Set([
  "NFO",
  "BFO",
  "MCX",
  "CDS",
  "BCD",
]);

/** Exchanges whose contracts carry option strikes. */
export const OPTIONS_EXCHANGES: ReadonlySet<string> = new Set(["NFO", "BFO"]);

/** True when the exchange requires lot-multiple quantities. */
export function isDerivativeExchange(exchange: string): boolean {
  return DERIVATIVE_EXCHANGES.has(exchange);
}

// ---------------------------------------------------------------------------
// Mode
// ---------------------------------------------------------------------------

/**
 * Refuse order entry outside a mode that can place one.
 *
 * Live-intent order entry is refused in Explore — every price on screen is
 * demo data and there is no broker. Practice routes to the native sandbox
 * and is allowed. Order Pad's Practice Buy is the paper exception: it must
 * not call this guard, so Explore can record a sample fill without a live
 * broker. The backend still 403s Explore JWT writes (`mode_blocked`); this
 * guard exists so Live-intent surfaces tell the operator before a round trip.
 */
export function checkOrderEntryMode(mode: AppMode): string | null {
  if (mode === "explore") return "Connect a broker to place orders";
  return null;
}

// ---------------------------------------------------------------------------
// Lot size
// ---------------------------------------------------------------------------

export interface LotSizeState {
  /** Lot size resolved from the backend symbol master, or null/0 when unknown. */
  lotSize: number | null;
  /**
   * Whether the lot size was confirmed by the backend for THIS contract.
   * A hardcoded fallback table must never set this — lot sizes change, and a
   * stale value mis-sizes every order placed against it.
   */
  verified: boolean;
}

/**
 * Refuse a derivative order whose lot size has not been confirmed.
 *
 * Non-derivative exchanges are unconstrained (equity quantity is in shares).
 */
export function checkLotSizeVerified(
  exchange: string,
  { lotSize, verified }: LotSizeState,
  symbol: string,
): string | null {
  if (!isDerivativeExchange(exchange)) return null;
  if (!verified || lotSize == null || lotSize <= 0) {
    return `Not placed. The lot size for ${symbol} isn't verified.`;
  }
  return null;
}

/**
 * Refuse a derivative quantity that is not a positive multiple of the lot size.
 *
 * Runs the verification check first, so a caller gets one refusal covering both
 * "no confirmed lot size" and "quantity is not a whole number of lots".
 */
export function checkLotMultiple(
  exchange: string,
  quantity: number,
  state: LotSizeState,
  symbol: string,
): string | null {
  const unverified = checkLotSizeVerified(exchange, state, symbol);
  if (unverified) return unverified;
  if (!isDerivativeExchange(exchange)) return null;
  const lotSize = state.lotSize as number;
  if (!Number.isFinite(quantity) || quantity <= 0 || quantity % lotSize !== 0) {
    return lotMultipleRefusal(lotSize);
  }
  return null;
}

/**
 * Resolve the real order quantity from a lot count.
 *
 * Returns null when a derivative's lot size is unconfirmed — the caller must
 * then refuse the order rather than fall back to a lot size of 1, which would
 * send a single share/unit where the operator asked for a lot.
 */
export function resolveLotQuantity(
  exchange: string,
  lots: number,
  { lotSize, verified }: LotSizeState,
): number | null {
  if (isDerivativeExchange(exchange)) {
    if (!verified || lotSize == null || lotSize <= 0) return null;
    return lots * lotSize;
  }
  // Equities report a lot size of 0 or 1 — quantity is the lot count itself
  // unless the backend gave a genuine multiplier.
  return lots * (lotSize != null && lotSize > 0 ? lotSize : 1);
}

// ---------------------------------------------------------------------------
// Price / trigger
// ---------------------------------------------------------------------------

export type GuardedOrderType = "MARKET" | "LIMIT" | "SL" | "SL-M";

/** Order types that carry an operator-set limit price. */
export const PRICE_REQUIRED: ReadonlySet<GuardedOrderType> = new Set<GuardedOrderType>([
  "LIMIT",
  "SL",
]);

/** Order types that carry an operator-set trigger price. */
export const TRIGGER_REQUIRED: ReadonlySet<GuardedOrderType> = new Set<GuardedOrderType>([
  "SL",
  "SL-M",
]);

/**
 * Refuse an order whose price fields are missing for its type.
 *
 * A LIMIT or SL order must carry a real price: ₹0 is a guaranteed broker
 * rejection, and a lenient bridge could treat it as marketable — turning a
 * price-protected order into an unprotected market order. Two surfaces
 * (Order Pad, Quick Trade) previously sent exactly that.
 */
export function checkPriceForOrderType(
  orderType: GuardedOrderType,
  price: number | null | undefined,
  triggerPrice?: number | null,
): string | null {
  if (PRICE_REQUIRED.has(orderType)) {
    if (price == null || !Number.isFinite(price) || price <= 0) {
      return `Enter a price above zero before placing a ${orderType} order`;
    }
  }
  if (TRIGGER_REQUIRED.has(orderType)) {
    if (triggerPrice == null || !Number.isFinite(triggerPrice) || triggerPrice <= 0) {
      return `Enter a trigger price above zero before placing a ${orderType} order`;
    }
  }
  return null;
}

/**
 * Single-order quantity ceilings.
 *
 * These match SafetySystem L1 `_DEFAULT_QTY_LIMITS`. An unknown exchange uses
 * the same 50,000 fallback as the server. The refusal sentence matches L1 so
 * the pad and the gate tell the operator the same thing.
 */
export const ORDER_QUANTITY_LIMITS: Readonly<Record<string, number>> = {
  NSE: 50_000,
  BSE: 50_000,
  NFO: 5_000,
  BFO: 5_000,
  MCX: 1_000,
  CDS: 10_000,
  BCD: 10_000,
  NCDEX: 5_000,
  NCO: 5_000,
};

const DEFAULT_ORDER_QUANTITY_LIMIT = 50_000;

/** Exchange ceiling, or the L1 default when the segment is not listed. */
export function orderQuantityLimit(exchange: string): number {
  return ORDER_QUANTITY_LIMITS[exchange.trim().toUpperCase()] ?? DEFAULT_ORDER_QUANTITY_LIMIT;
}

/**
 * Refuse a quantity above the exchange ceiling.
 *
 * Returns null for non-positive values so the existing minimum check owns
 * that sentence. The visible message is the L1 sentence.
 */
export function checkOrderQuantityLimit(exchange: string, quantity: number): string | null {
  if (!Number.isInteger(quantity) || quantity < 1) return null;
  const limit = orderQuantityLimit(exchange);
  if (quantity <= limit) return null;
  const label = exchange.trim().toUpperCase() || exchange;
  return `Quantity ${quantity} exceeds ${label} limit of ${limit}`;
}

/**
 * NSE index quantity freeze limits.
 *
 * NSE/FAOP/76693 (1 October 2026, effective 5 October 2026). These apply
 * when the broker does not send `freeze_qty`. An order above the limit is
 * refused whole. It is not split.
 */
export const NSE_INDEX_FREEZE_QUANTITY: Readonly<Record<string, number>> = {
  NIFTY: 3510,
  BANKNIFTY: 1440,
  FINNIFTY: 3240,
  MIDCPNIFTY: 5760,
  NIFTYNXT50: 1125,
  NIFTYFPI: 53900,
};

const INDEX_FREEZE_NAMES = Object.keys(NSE_INDEX_FREEZE_QUANTITY).sort(
  (left, right) => right.length - left.length,
);

/** Index name inside a contract symbol. Longer names win over `NIFTY`. */
export function indexUnderlying(symbol: string): string | null {
  const compact = symbol.toUpperCase().replace(/\s+/g, "");
  if (!compact) return null;
  for (const name of INDEX_FREEZE_NAMES) {
    if (compact === name || compact.startsWith(name)) return name;
  }
  return null;
}

/** Symbol named in the freeze refusal. */
export function orderSymbolLabel(symbol: string): string {
  const text = symbol.trim().replace(/\s+/g, " ");
  return text || "this contract";
}

/** Same lot sentence as order admission. Shown under Quantity in Practice and Live. */
export function lotMultipleRefusal(lotSize: number): string {
  return `Quantity must be a multiple of the lot size (${lotSize}).`;
}

/** Same freeze sentence as order admission. The number is the broker freeze when one was sent. */
export function freezeQuantityRefusal(symbol: string, freeze: number): string {
  return `Max ${freeze} per order for ${orderSymbolLabel(symbol)}. Place smaller orders.`;
}

/**
 * Broker freeze quantity when it is a positive whole number, otherwise the
 * NSE/FAOP/76693 index table.
 */
export function resolveFreezeQuantity(
  symbol: string,
  brokerFreezeQty?: number | null,
): number | null {
  if (typeof brokerFreezeQty === "number" && Number.isInteger(brokerFreezeQty) && brokerFreezeQty > 0) {
    return brokerFreezeQty;
  }
  const underlying = indexUnderlying(symbol);
  if (!underlying) return null;
  return NSE_INDEX_FREEZE_QUANTITY[underlying] ?? null;
}

/**
 * Refuse a quantity above the freeze quantity.
 *
 * Returns null for non-positive values so the minimum check owns that
 * sentence. The visible message matches order admission.
 */
export function checkFreezeQuantity(
  symbol: string,
  quantity: number,
  brokerFreezeQty?: number | null,
): string | null {
  if (!Number.isInteger(quantity) || quantity < 1) return null;
  const limit = resolveFreezeQuantity(symbol, brokerFreezeQty);
  if (limit == null || quantity <= limit) return null;
  return freezeQuantityRefusal(symbol, limit);
}

// ---------------------------------------------------------------------------
// Strict numeric parsers
// ---------------------------------------------------------------------------

/**
 * Parse a positive whole number ("1,000" → 1000); null for anything else.
 *
 * Deliberately stricter than parseInt, which happily truncates "12abc" to 12.
 */
export function parseWholeNumber(raw: string): number | null {
  const digits = raw.trim().replace(/,/g, "");
  if (!/^\d+$/.test(digits)) return null;
  const value = Number.parseInt(digits, 10);
  return value > 0 ? value : null;
}

/** Parse a non-negative price ("123.45"); null for garbage or negatives. */
export function parsePriceValue(raw: string): number | null {
  const trimmed = raw.trim().replace(/,/g, "");
  if (!/^\d+(\.\d+)?$/.test(trimmed)) return null;
  return Number.parseFloat(trimmed);
}

// ---------------------------------------------------------------------------
// Broker order identity
// ---------------------------------------------------------------------------

/**
 * Extract a real broker order id from a place-order result.
 *
 * A cancel/modify must never be attempted against a fabricated id. broker
 * returns the id under `orderId`/`orderid`/`order_id` (or as a bare string for
 * lenient bridges); anything else yields null so the caller fails closed.
 */
export function extractBrokerOrderId(result: unknown): string | null {
  if (typeof result === "string") return result.trim() !== "" ? result : null;
  if (result == null || typeof result !== "object") return null;
  const rec = result as { orderId?: unknown; orderid?: unknown; order_id?: unknown };
  const candidate = rec.orderId ?? rec.orderid ?? rec.order_id;
  if (typeof candidate === "string" && candidate.trim() !== "") return candidate;
  if (typeof candidate === "number") return String(candidate);
  return null;
}

/**
 * Whether a broker order status is terminal — the order has left the book
 * (filled, rejected or cancelled) and can no longer be cancelled or modified.
 *
 * Pending variants ("open pending", "trigger pending", "cancel pending") and
 * partial fills are NOT terminal: the order is still live at the broker.
 */
export function isTerminalOrderStatus(status: string): boolean {
  const s = status.toLowerCase();
  if (s.includes("pending") || s.includes("partial")) return false;
  return (
    s.includes("complete") ||
    s.includes("filled") ||
    s.includes("executed") ||
    s.includes("rejected") ||
    s.includes("cancelled") ||
    s.includes("canceled")
  );
}

/** Whether an order is still open at the broker (the inverse of terminal). */
export function isOpenOrderStatus(status: string): boolean {
  return !isTerminalOrderStatus(status);
}

// ---------------------------------------------------------------------------
// Large-order confirmation
// ---------------------------------------------------------------------------

/**
 * Lot count at or above which a surface should ask for confirmation before
 * sending. A fat-fingered lot count is the single most common costly slip on a
 * one-click ticket.
 */
export const LARGE_ORDER_LOTS = 10;

/** Whether this lot count warrants an explicit confirmation step. */
export function needsLargeOrderConfirmation(lots: number): boolean {
  return Number.isFinite(lots) && lots >= LARGE_ORDER_LOTS;
}
