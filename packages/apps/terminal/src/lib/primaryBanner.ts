/**
 * FT-UX-001 — at most one primary banner.
 *
 * Kinds feed the incident strip between the TopBar and the Mode line.
 * Mode honesty owns Explore and Practice, so this slot stays empty there.
 * On Live: Live risk / Kill All, then host (network_local, host_unhealthy,
 * backend_unreachable), then broker trust, then a disconnected feed, then
 * edge, then Chat (llm_provider). Laya Down ranks with broker trust.
 * Host beats broker inside the incident
 * classifier. Toasts stay action feedback and must not duplicate this strip.
 */

import type { FailureClass, OperatorIncident } from "@/lib/operatorIncident";
import type { AppMode } from "@/stores/modeStore";

export type PrimaryBannerKind =
  | "live_risk"
  | "feed_disconnected"
  | FailureClass
  | null;

export const LIVE_RISK_BANNER = "Live risk — kill switch or daily-loss alert is active";
export const FEED_DISCONNECTED_BANNER = "Live market feed disconnected";

export function selectPrimaryBanner(input: {
  mode: AppMode;
  liveRiskActive?: boolean;
  feedDisconnected?: boolean;
  incident?: OperatorIncident | null;
}): PrimaryBannerKind {
  if (input.mode !== "live") return null;
  if (input.liveRiskActive) return "live_risk";
  const incident = input.incident ?? null;
  const incidentOutranksFeed = incident !== null && incidentRank(incident.failureClass) >= 2;
  if (incidentOutranksFeed) return incident.failureClass;
  if (input.feedDisconnected) return "feed_disconnected";
  if (incident) return incident.failureClass;
  return null;
}

/** 3 host, 2 broker trust, 1 edge, 0 Chat. Feed sits between 2 and 1. */
function incidentRank(failureClass: FailureClass): number {
  if (
    failureClass === "network_local"
    || failureClass === "host_unhealthy"
    || failureClass === "backend_unreachable"
  ) {
    return 3;
  }
  if (failureClass === "edge") return 1;
  if (failureClass === "llm_provider") return 0;
  // Broker trust and Laya Down. Both close Live place and mirror. Kill All stays reachable.
  return 2;
}

export function primaryBannerCopy(kind: PrimaryBannerKind): string | null {
  if (kind === "live_risk") return LIVE_RISK_BANNER;
  if (kind === "feed_disconnected") return FEED_DISCONNECTED_BANNER;
  return null;
}
