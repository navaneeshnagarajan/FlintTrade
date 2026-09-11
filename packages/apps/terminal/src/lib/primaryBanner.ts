/**
 * FT-UX-001 — at most one primary banner.
 *
 * Priority: Explore sample > Live risk > feed disconnected.
 * Toasts stay action feedback and must not duplicate this strip.
 */

import type { AppMode } from "@/stores/modeStore";

export type PrimaryBannerKind =
  | "explore_sample"
  | "practice_sample"
  | "live_risk"
  | "feed_disconnected"
  | null;

export const EXPLORE_SAMPLE_BANNER = "EXPLORE MODE — All data shown is sample only";
export const PRACTICE_SAMPLE_BANNER =
  "PRACTICE MODE — Virtual trading results are simulated and do not represent actual trading outcomes";
export const LIVE_RISK_BANNER = "Live risk — kill switch or daily-loss alert is active";
export const FEED_DISCONNECTED_BANNER = "Live market feed disconnected";

export function selectPrimaryBanner(input: {
  mode: AppMode;
  liveRiskActive?: boolean;
  feedDisconnected?: boolean;
}): PrimaryBannerKind {
  if (input.mode === "explore") return "explore_sample";
  if (input.mode === "practice") return "practice_sample";
  if (input.liveRiskActive) return "live_risk";
  if (input.feedDisconnected) return "feed_disconnected";
  return null;
}

export function primaryBannerCopy(kind: PrimaryBannerKind): string | null {
  if (kind === "explore_sample") return EXPLORE_SAMPLE_BANNER;
  if (kind === "practice_sample") return PRACTICE_SAMPLE_BANNER;
  if (kind === "live_risk") return LIVE_RISK_BANNER;
  if (kind === "feed_disconnected") return FEED_DISCONNECTED_BANNER;
  return null;
}
