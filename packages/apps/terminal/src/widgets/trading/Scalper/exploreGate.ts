/**
 * Explore Scalper external-action gate (FT-TRADE-009).
 *
 * Same honesty class as Automate Telegram Send Test: Explore never opens
 * Confirm Order and never places. Practice / Live keep the Confirm path.
 */

import type { AppMode } from "@/stores/modeStore";

export const EXPLORE_SCALPER_ORDER_HELPER =
  "Orders blocked in Explore (sample-only). Switch to Practice or Live with a broker connected to trade.";

export const EXPLORE_ONE_CLICK_TITLE = "One-click unavailable in Explore";

/** True when Scalper may open Confirm or accept a one-click place. */
export function scalperOrdersArmed(mode: AppMode): boolean {
  return mode !== "explore";
}
