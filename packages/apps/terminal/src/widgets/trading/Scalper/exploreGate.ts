/**
 * Explore Scalper external-action gate.
 *
 * Same honesty class as Automate Telegram Send Test: Explore never opens
 * Confirm Order and never places. Practice / Live keep the Confirm path.
 */

import type { SessionMode } from "@/lib/modeClaim";

export const EXPLORE_SCALPER_ORDER_HELPER =
  "Orders are blocked for Example. Switch to Practice or Live with a broker connected to trade.";

export const UNAVAILABLE_SCALPER_ORDER_HELPER =
  "Orders are blocked because the session mode couldn't be confirmed. Sign in again or reload.";

export const EXPLORE_ONE_CLICK_TITLE = "One-click is unavailable for Example";

export const UNAVAILABLE_ONE_CLICK_TITLE =
  "One-click is unavailable because the session mode couldn't be confirmed. Sign in again or reload.";

/** True when Scalper may open Confirm or accept a one-click place. */
export function scalperOrdersArmed(mode: SessionMode): boolean {
  return mode === "practice" || mode === "live";
}

/** Why Scalper orders stay blocked. Null when Practice or Live may place. */
export function scalperOrderBlockCopy(mode: SessionMode): string | null {
  if (scalperOrdersArmed(mode)) return null;
  if (mode === "unavailable") return UNAVAILABLE_SCALPER_ORDER_HELPER;
  return EXPLORE_SCALPER_ORDER_HELPER;
}

/** Title for the locked one-click control. Example only for the example claim. */
export function scalperOneClickTitle(mode: SessionMode): string {
  if (mode === "unavailable") return UNAVAILABLE_ONE_CLICK_TITLE;
  return EXPLORE_ONE_CLICK_TITLE;
}
