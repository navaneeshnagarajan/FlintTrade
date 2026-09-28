/**
 * Laya chip and the Mode-menu Live reason.
 *
 * The chip label follows the current mode. Practice and Explore show the
 * sidecar. Live shows the Live-facing status. Qualification is a tooltip
 * and the disabled-Live reason, not a Down label while Practice can admit.
 */

export type LayaStatus = "ready" | "degraded" | "down";

/** Disabled-Live reason for the Mode menu when the sidecar is up and Live is not qualified. */
export const LAYA_NOT_QUALIFIED_FOR_LIVE = "Not qualified for Live";

export function layaChipStatus(input: {
  mode: string;
  practice: LayaStatus | null | undefined;
  live: LayaStatus | null | undefined;
}): LayaStatus | null {
  if (input.mode === "live") return input.live ?? null;
  return input.practice ?? null;
}

/**
 * Reason Live stays disabled while Practice or Explore can still use the sidecar.
 * Actual Down is the chip label, not this line.
 */
export function layaDisabledLiveReason(input: {
  practice: LayaStatus | null | undefined;
  liveQualified: boolean;
}): string | null {
  if (input.liveQualified) return null;
  if (input.practice !== "ready" && input.practice !== "degraded") return null;
  return LAYA_NOT_QUALIFIED_FOR_LIVE;
}
