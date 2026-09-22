/**
 * Incident banner for the slot under TopBar.
 *
 * Mode honesty is a separate always-on line and is not selected here.
 * Explore and Practice leave this slot empty. On Live, risk beats a
 * disconnected feed so the desk shows at most one incident.
 */

import type { AppMode } from "@/stores/modeStore";

export type PrimaryBannerKind = "live_risk" | "feed_disconnected" | null;

export const LIVE_RISK_BANNER = "Live risk — kill switch or daily-loss alert is active";
export const FEED_DISCONNECTED_BANNER = "Live market feed disconnected";

export function selectPrimaryBanner(input: {
  mode: AppMode;
  liveRiskActive?: boolean;
  feedDisconnected?: boolean;
}): PrimaryBannerKind {
  if (input.mode !== "live") return null;
  if (input.liveRiskActive) return "live_risk";
  if (input.feedDisconnected) return "feed_disconnected";
  return null;
}

export function primaryBannerCopy(kind: PrimaryBannerKind): string | null {
  if (kind === "live_risk") return LIVE_RISK_BANNER;
  if (kind === "feed_disconnected") return FEED_DISCONNECTED_BANNER;
  return null;
}
