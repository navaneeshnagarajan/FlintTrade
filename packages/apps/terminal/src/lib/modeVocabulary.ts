/**
 * FT-UX-001 — execution-mode vocabulary.
 *
 * Explore / Practice / Live chips mean execution mode only. Example data is
 * labelled Example; Practice wording stays on the Practice sandbox path; Live
 * wording is reserved for real broker orders. Market-session copy lives in
 * `market.ts` and must not be reused here.
 */

import type { AppMode } from "@/stores/modeStore";

export type OrderSide = "BUY" | "SELL";

/** Order Pad submit label. Explore never says Practice or Live. */
export function orderPadCtaLabel(mode: AppMode, action: OrderSide): string {
  if (mode === "explore") {
    return action === "BUY" ? "Example Buy" : "Example Sell";
  }
  if (mode === "practice") {
    return action === "BUY" ? "Practice Buy" : "Practice Sell";
  }
  return `Place ${action} Order`;
}

/** Review dialog title. Explore uses Example wording. */
export function orderReviewTitle(mode: AppMode): string {
  return mode === "explore" ? "Review Example order" : "Review Practice order";
}

export function orderReviewDescription(mode: AppMode): string {
  if (mode === "explore") {
    return "Example only. No broker or native trading API is contacted. Example records an example fill.";
  }
  return "Confirm places this simulated order.";
}

export function orderReviewDetailsLabel(mode: AppMode): string {
  return mode === "explore" ? "Example order details" : "Practice order details";
}

export function orderReviewConfirmAria(mode: AppMode): string {
  return mode === "explore" ? "Confirm Example order" : "Confirm simulated Practice order";
}

export function orderSuccessToast(mode: AppMode, orderId?: string): string {
  const suffix = orderId ? ` · ID: ${orderId}` : "";
  if (mode === "explore") return `Example order placed${suffix}`;
  return `Order placed${suffix}`;
}

export function orderSuccessNotificationTitle(
  mode: AppMode,
  action: string,
  quantity: number,
  symbol: string,
): string {
  const body = `${action} ${quantity} ${symbol}`;
  if (mode === "explore") return `Example order placed: ${body}`;
  return `Order placed: ${body}`;
}

export function orderSuccessNotificationBody(mode: AppMode, orderId?: string): string {
  if (mode === "explore") return "Example fill — no broker contacted.";
  return orderId ? `Order ID ${orderId}` : "Submitted to the broker.";
}

/** Order Pad session chip — session status, never Live mode. */
export const SESSION_OPEN_LABEL = "Session open";

/** Options premium hint. Explore never says Live. */
export function optionPremiumHint(mode: AppMode, ltp: number): string {
  const amount = ltp.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  if (mode === "explore") {
    return ltp > 0
      ? `Example premium ₹${amount} — prefills the LIMIT/SL price field.`
      : "Example premium unavailable — enter the limit price manually.";
  }
  if (mode === "practice") {
    return ltp > 0
      ? `Sandbox premium ₹${amount} — prefills the LIMIT/SL price field.`
      : "Sandbox premium unavailable — enter the limit price manually.";
  }
  return ltp > 0
    ? `Live premium ₹${amount} — prefills the LIMIT/SL price field.`
    : "Live premium unavailable — enter the limit price manually.";
}
