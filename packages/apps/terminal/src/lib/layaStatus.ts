/**
 * Laya chip and the Mode-menu Live reason.
 *
 * The chip label follows the current mode. Practice and Explore show the
 * sidecar. Live shows the Live-facing status. Qualification is a tooltip
 * and the disabled-Live reason, not a Down label while Practice can admit.
 * The first load keeps the label on Still loading so the chip does not
 * flash Down. Admission stays fail-closed for that wait.
 */

import { decisionSurfaceLabel } from "@/lib/deskStatus";

export type LayaStatus = "ready" | "degraded" | "down";

/** Disabled-Live reason for the Mode menu when the sidecar is up and Live is not qualified. */
export const LAYA_NOT_QUALIFIED_FOR_LIVE = "Not qualified for Live";

export const LAYA_REASON_CODES = [
  "not_started",
  "stopped",
  "port_in_use",
  "still_loading",
  "unreachable",
  "wrong_revision",
  "unverified",
  "identity_absent",
  "key_rejected",
] as const;

export type LayaReasonCode = (typeof LAYA_REASON_CODES)[number];

/** Next step shown with an operational reason. */
export const LAYA_START_COMMAND = "python -m flinttrade_core.laya_runtime start";

/** User guide section "Start Laya". The heading is written in the docs. */
export const LAYA_START_DOCS_HREF =
  "https://github.com/navaneeshnagarajan/FlintTrade/blob/main/docs/USER_GUIDE.md#start-laya";

export function layaChipStatus(input: {
  mode: string;
  practice: LayaStatus | null | undefined;
  live: LayaStatus | null | undefined;
}): LayaStatus | null {
  if (input.mode === "live") return input.live ?? null;
  return input.practice ?? null;
}

export function layaReasonPlain(reason: string | null | undefined, port: number): string | null {
  if (reason === "port_in_use") return `Port ${port} in use`;
  if (reason === "not_started") return "Not started";
  if (reason === "stopped") return "Stopped";
  if (reason === "still_loading") return "Still loading";
  if (reason === "unreachable") return "Unreachable";
  if (reason === "wrong_revision") return "Wrong model revision";
  if (reason === "unverified") return "Can't verify the model";
  if (reason === "identity_absent") return "Decision has no revision";
  if (reason === "key_rejected") return "API key rejected";
  return null;
}

/** Plain words plus the start command. The docs link sits beside the chip. */
export function layaReasonTooltip(reason: string | null | undefined, port: number): string | null {
  const plain = layaReasonPlain(reason, port);
  if (!plain) return null;
  return `${plain}. Next: ${LAYA_START_COMMAND}`;
}

/**
 * Chip label. Still loading replaces Down for the first model load.
 * Other states keep Ready, Degraded, or Down.
 */
export function layaChipLabel(input: {
  mode: string;
  practice: LayaStatus | null | undefined;
  live: LayaStatus | null | undefined;
  reason?: string | null;
}): "Ready" | "Degraded" | "Down" | "Still loading" {
  if (input.reason === "still_loading") return "Still loading";
  return decisionSurfaceLabel(layaChipStatus(input));
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
