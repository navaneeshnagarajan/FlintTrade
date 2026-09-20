/**
 * Risk Dashboard Kill All gate (FT-DITTO-003).
 *
 * Whenever Ditto risk runtime is unavailable — including Explore — Kill All
 * stays muted and disabled. Never the armed red emergency CTA in that state.
 * Empty-account disarm on a successful snapshot remains FT-DITTO-001.
 */

import type { AppMode } from "@/stores/modeStore";

export const RISK_RUNTIME_UNAVAILABLE_HELPER =
  "Risk runtime unavailable — Kill All disabled.";

export type RiskLoadState = "loading" | "error" | "ready";

export interface KillAllGateInput {
  mode: AppMode;
  riskLoadState: RiskLoadState;
  hasManagedAccounts: boolean;
}

/** Resolve whether the risk query returned a snapshot, failed, or is still pending. */
export function resolveRiskLoadState(input: {
  risk: { accounts?: unknown[] } | null | undefined;
  isError: boolean;
}): RiskLoadState {
  if (input.risk != null) return "ready";
  if (input.isError) return "error";
  return "loading";
}

/** Locked why-disabled reason when runtime is unavailable, or null when Live/Practice may arm. */
export function killAllHelper({
  mode,
  riskLoadState,
}: Pick<KillAllGateInput, "mode" | "riskLoadState">): string | null {
  if (mode === "explore") return RISK_RUNTIME_UNAVAILABLE_HELPER;
  if (riskLoadState !== "ready") return RISK_RUNTIME_UNAVAILABLE_HELPER;
  return null;
}

/** True when Live/Practice has a live runtime snapshot and at least one managed account. */
export function killAllArmed({
  mode,
  riskLoadState,
  hasManagedAccounts,
}: KillAllGateInput): boolean {
  return killAllHelper({ mode, riskLoadState }) === null && hasManagedAccounts;
}
