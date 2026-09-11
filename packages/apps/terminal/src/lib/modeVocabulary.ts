/**
 * FT-UX-001 — execution-mode vocabulary.
 *
 * Explore / Practice / Live chips mean execution mode only. Sample data is
 * labelled sample; Practice wording stays on the Practice sandbox path; Live
 * wording is reserved for real broker orders. Market-session copy lives in
 * `market.ts` and must not be reused here.
 */

import type { AppMode } from "@/stores/modeStore";

export type OrderSide = "BUY" | "SELL";

/** Order Pad submit label. Explore never says Practice or Live. */
export function orderPadCtaLabel(mode: AppMode, action: OrderSide): string {
  if (mode === "explore") {
    return action === "BUY" ? "Sample Buy" : "Sample Sell";
  }
  if (mode === "practice") {
    return action === "BUY" ? "Practice Buy" : "Practice Sell";
  }
  return `Place ${action} Order`;
}

/** Review dialog title. Explore uses sample wording. */
export function orderReviewTitle(mode: AppMode): string {
  return mode === "explore" ? "Review sample order" : "Review Practice order";
}

export function orderReviewDescription(mode: AppMode): string {
  if (mode === "explore") {
    return "Sample only. No broker or native trading API is contacted. Explore records a local sample fill.";
  }
  return "Simulation only. No broker or native trading API is contacted. Practice sends this to FlintTrade's sandbox; Explore records a sample fill.";
}

export function orderReviewDetailsLabel(mode: AppMode): string {
  return mode === "explore" ? "Sample order details" : "Practice order details";
}

export function orderReviewConfirmAria(mode: AppMode): string {
  return mode === "explore" ? "Confirm sample order" : "Confirm simulated Practice order";
}

export function orderSuccessToast(mode: AppMode, orderId?: string): string {
  const suffix = orderId ? ` · ID: ${orderId}` : "";
  if (mode === "explore") return `Sample order placed${suffix}`;
  return `Order placed${suffix}`;
}

export function orderSuccessNotificationTitle(
  mode: AppMode,
  action: string,
  quantity: number,
  symbol: string,
): string {
  const body = `${action} ${quantity} ${symbol}`;
  if (mode === "explore") return `Sample order placed: ${body}`;
  return `Order placed: ${body}`;
}

export function orderSuccessNotificationBody(mode: AppMode, orderId?: string): string {
  if (mode === "explore") return "Explore sample fill — no broker contacted.";
  return orderId ? `Order ID ${orderId}` : "Submitted to the broker.";
}

/** Order Pad session chip — session status, never Live mode. */
export const SESSION_OPEN_LABEL = "Session open";
