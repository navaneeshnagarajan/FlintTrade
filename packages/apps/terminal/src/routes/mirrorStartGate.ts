/**
 * Position Mirror Start external-action gate (FT-DITTO-002).
 *
 * Same honesty class as Telegram Send Test / Explore Scalper: the Start CTA
 * never looks armed when mirroring is unavailable. Explore is always
 * sample-only.
 */

import type { AppMode } from "@/stores/modeStore";

export const EXPLORE_MIRROR_START_HELPER =
  "Mirroring blocked in Explore (sample-only). Switch to Practice or Live with broker accounts connected.";

export const MIRROR_START_SELECT_HELPER =
  "Select a source account and at least one target to start mirroring.";

export const MIRROR_START_CONNECT_HELPER =
  "Connect a source and at least one target account to start mirroring.";

export interface MirrorStartGateInput {
  mode: AppMode;
  sourceAccount: string;
  targetCount: number;
  activeAccountCount: number;
}

/** One locked why-disabled reason, or null when Start may arm. */
export function mirrorStartHelper({
  mode,
  sourceAccount,
  targetCount,
  activeAccountCount,
}: MirrorStartGateInput): string | null {
  if (mode === "explore") return EXPLORE_MIRROR_START_HELPER;
  if (activeAccountCount === 0) return MIRROR_START_CONNECT_HELPER;
  if (!sourceAccount.trim() || targetCount < 1) return MIRROR_START_SELECT_HELPER;
  return null;
}

/** True when Practice/Live have a source, ≥1 target, and broker accounts ready. */
export function mirrorStartArmed(input: MirrorStartGateInput): boolean {
  return mirrorStartHelper(input) === null;
}
