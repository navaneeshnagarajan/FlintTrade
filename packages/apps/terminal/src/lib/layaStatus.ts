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
  "downloading",
  "download_failed",
  "unreachable",
  "wrong_revision",
  "unverified",
  "key_rejected",
  "key_missing",
] as const;

export type LayaReasonCode = (typeof LAYA_REASON_CODES)[number];

/** Next step shown with an operational reason. */
export const LAYA_START_COMMAND = "python -m flinttrade_core.laya_runtime start";

/** Decimal gigabytes, matching the Python progress line. */
const DECIMAL_GB = 1_000_000_000;

export const LAYA_DOWNLOAD_FAILED_DETAIL = "Can't download the model";
export const LAYA_DOWNLOAD_FAILED_TOOLTIP = "Check your connection, then Start Laya again.";

/** Live download line. One decimal place, decimal gigabytes. */
export function formatDownloadProgress(doneBytes: number, totalBytes: number): string {
  const done = (doneBytes / DECIMAL_GB).toFixed(1);
  const total = (totalBytes / DECIMAL_GB).toFixed(1);
  return `Downloading the model · ${done} of ${total} GB`;
}

/** Desk poll for the same Laya status the order gate reads. Matches the 1.5s watch. */
export const LAYA_STATUS_POLL_MS = 1_500;

/** Chip label while a stop or start has not been confirmed. */
export const LAYA_CHECKING_LABEL = "Checking";

/** Popover line for that unconfirmed window. Neutral colour, not Ready. */
export const LAYA_CHECKING_DETAIL = "Checking Laya…";

/** Exact order refusal when the gate says Laya is Down. */
export const LAYA_DOWN_PAUSE = "Laya is Down. New orders are paused until it's Ready. You can still close positions.";

/** True when a failed place is the Down pause. Other denials leave the chip alone. */
export function layaOrderRefused(body: unknown): boolean {
  if (body === null || typeof body !== "object") return false;
  const record = body as { code?: unknown; message?: unknown; reason?: unknown };
  if (record.code !== "laya_denied") return false;
  return record.message === LAYA_DOWN_PAUSE || record.reason === LAYA_DOWN_PAUSE;
}

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

export function layaReasonPlain(
  reason: string | null | undefined,
  port: number,
  downloadBytes?: number | null,
  downloadTotal?: number | null,
): string | null {
  if (reason === "port_in_use") return `Port ${port} in use`;
  if (reason === "not_started") return "Not started";
  if (reason === "stopped") return "Stopped";
  if (reason === "still_loading") return "Still loading";
  if (reason === "downloading") return formatDownloadProgress(downloadBytes ?? 0, downloadTotal ?? 0);
  if (reason === "download_failed") return LAYA_DOWNLOAD_FAILED_DETAIL;
  if (reason === "unreachable") return "Unreachable";
  if (reason === "wrong_revision") return "Wrong model version";
  if (reason === "unverified") return "Can't verify the model";
  if (reason === "key_rejected") return "Can't reach Laya";
  if (reason === "key_missing") return "The Laya API key file is missing.";
  return null;
}

const LAYA_REASON_TOOLTIPS: Record<string, string> = {
  unverified:
    "The installed model couldn't be checked against the pinned version. Restart Laya. If it keeps happening, reinstall it.",
  wrong_revision: "Laya is running a different model than FlintTrade expects.",
  key_rejected: "Laya restarted with a new key. Reconnecting…",
  key_missing: "The Laya API key file is missing.",
  download_failed: LAYA_DOWNLOAD_FAILED_TOOLTIP,
};

/** Hover text. Model, key, and download failures keep their own sentence. Downloading has none. */
export function layaReasonTooltip(reason: string | null | undefined, port: number): string | null {
  if (reason === "downloading") return null;
  if (reason && reason in LAYA_REASON_TOOLTIPS) return LAYA_REASON_TOOLTIPS[reason];
  const plain = layaReasonPlain(reason, port);
  if (!plain) return null;
  return `${plain}. Next: ${LAYA_START_COMMAND}`;
}

/**
 * Status-menu detail for a wrong model version. The chip stays
 * "Wrong model version" and does not use this sentence.
 */
export const OLLAMA_DIGEST_DETAIL =
  "FlintTrade checks the digest Ollama reports for the exact model tag on every admission. The tag is not the proof. If that digest does not match the pinned digest, the gate shows Wrong model version and new orders stay paused. You can still close positions.";

/** Next line when a FlintTrade-managed Ollama install is not running. */
export const OLLAMA_NOT_STARTED_MANAGED = "Ollama isn't running. Start it to bring Laya back.";

/** Next line when Ollama is the operator's own install. There is no Start action. */
export const OLLAMA_NOT_STARTED_UNMANAGED = "Ollama isn't running. Start Ollama on this computer, then try again.";

export const OLLAMA_START_ACTION = "Start Laya";
export const OLLAMA_STARTING_ACTION = "Starting…";
export const OLLAMA_START_FAILED = "Laya could not be started.";

/** Chip words on the Ollama route. Identical to the sidecar chip. */
export function ollamaChipText(
  reason: string | null | undefined,
  port: number,
  downloadBytes?: number | null,
  downloadTotal?: number | null,
): string | null {
  return layaReasonPlain(reason, port, downloadBytes, downloadTotal);
}

export function ollamaNotStartedLine(managed: boolean): string {
  return managed ? OLLAMA_NOT_STARTED_MANAGED : OLLAMA_NOT_STARTED_UNMANAGED;
}

/** Status-menu detail. Absent for reasons that keep the sidecar tooltip. */
export function ollamaStatusMenuDetail(reason: string | null | undefined, managed: boolean): string | null {
  if (reason === "wrong_revision") return OLLAMA_DIGEST_DETAIL;
  if (reason === "not_started") return ollamaNotStartedLine(managed);
  return null;
}

/** Hover text on the Ollama route. It never names the sidecar start command. */
export function ollamaRouteTooltip(
  reason: string | null | undefined,
  port: number,
  managed: boolean,
): string | null {
  if (reason === "not_started") return ollamaNotStartedLine(managed);
  const tooltip = layaReasonTooltip(reason, port);
  if (tooltip?.includes(LAYA_START_COMMAND)) return layaReasonPlain(reason, port);
  return tooltip;
}

/** Every sentence the Ollama route can show the operator. */
export function ollamaRouteVisibleLines(managed: boolean): string[] {
  const lines: string[] = [];
  for (const reason of LAYA_REASON_CODES) {
    const chip = ollamaChipText(
      reason,
      11434,
      reason === "downloading" ? 1_200_000_000 : 0,
      reason === "downloading" ? 3_400_000_000 : 0,
    );
    if (chip) lines.push(chip);
    const detail = ollamaStatusMenuDetail(reason, managed);
    if (detail) lines.push(detail);
    const tooltip = ollamaRouteTooltip(reason, 11434, managed);
    if (tooltip && tooltip !== chip && tooltip !== detail) lines.push(tooltip);
  }
  lines.push(LAYA_CHECKING_DETAIL, LAYA_DOWN_PAUSE, OLLAMA_START_FAILED);
  if (managed) lines.push(OLLAMA_START_ACTION, OLLAMA_STARTING_ACTION);
  for (const label of ["Ready", "Degraded", "Down", "Still loading", "Checking"]) {
    lines.push(`Laya ${label}`);
  }
  return lines;
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
  checking?: boolean;
}): "Ready" | "Degraded" | "Down" | "Still loading" | "Checking" {
  if (input.checking) return LAYA_CHECKING_LABEL;
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
