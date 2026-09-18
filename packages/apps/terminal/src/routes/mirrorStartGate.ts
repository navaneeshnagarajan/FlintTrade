/**
 * Position Mirror Start external-action gate (FT-DITTO-002).
 *
 * Same honesty class as Telegram Send Test / Explore Scalper: the Start CTA
 * never looks armed when mirroring is unavailable. Explore is always
 * sample-only. Practice stays disarmed — the backend is Live-only.
 */

import type { AppMode } from "@/stores/modeStore";

export const EXPLORE_MIRROR_START_HELPER =
  "Mirroring blocked in Explore (sample-only). Switch to Practice or Live with broker accounts connected.";

export const PRACTICE_MIRROR_START_HELPER =
  "Mirroring requires Live with broker accounts connected.";

export const MIRROR_START_SELECT_HELPER =
  "Select a source account and at least one target to start mirroring.";

export const MIRROR_START_CONNECT_HELPER =
  "Connect a source and at least one target account to start mirroring.";

export const MIRROR_START_LOADING_HELPER = "Loading accounts...";

export const MIRROR_START_ERROR_HELPER = "Could not load accounts.";

export type AccountsLoadState = "loading" | "error" | "ready";

export interface MirrorStartGateInput {
  mode: AppMode;
  sourceAccount: string;
  targetCount: number;
  activeAccountCount: number;
  accountsLoadState: AccountsLoadState;
}

/** Resolve whether the accounts query has a successful list, failed, or is still pending. */
export function resolveAccountsLoadState(input: {
  accounts: { accounts?: unknown[] } | undefined;
  isError: boolean;
}): AccountsLoadState {
  if (Array.isArray(input.accounts?.accounts)) return "ready";
  if (input.isError) return "error";
  return "loading";
}

/** One locked why-disabled reason, or null when Start may arm. */
export function mirrorStartHelper({
  mode,
  sourceAccount,
  targetCount,
  activeAccountCount,
  accountsLoadState,
}: MirrorStartGateInput): string | null {
  if (mode === "explore") return EXPLORE_MIRROR_START_HELPER;
  if (mode === "practice") return PRACTICE_MIRROR_START_HELPER;
  if (accountsLoadState === "loading") return MIRROR_START_LOADING_HELPER;
  if (accountsLoadState === "error") return MIRROR_START_ERROR_HELPER;
  if (activeAccountCount === 0) return MIRROR_START_CONNECT_HELPER;
  if (!sourceAccount.trim() || targetCount < 1) return MIRROR_START_SELECT_HELPER;
  return null;
}

/** True when Live has a source, ≥1 target, and broker accounts ready. */
export function mirrorStartArmed(input: MirrorStartGateInput): boolean {
  return mirrorStartHelper(input) === null;
}
