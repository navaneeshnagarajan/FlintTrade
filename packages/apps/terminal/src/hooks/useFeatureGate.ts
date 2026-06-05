import { useSkillLevel } from "./useSkillLevel";
import { FEATURE_GATES } from "@/lib/featureGates";
import type { Domain } from "@/types/skill";

export type GateStatus = "visible" | "preview" | "locked";

/** Returns gate status for a feature based on current skill level. */
export function useFeatureGate(featureId: string, domain?: Domain): GateStatus {
  const level = useSkillLevel(domain);
  const gate = FEATURE_GATES[featureId];
  if (!gate) {
    // A `widget:` id that reaches a gate check has already passed the
    // skill-tier allowlist (useSkillContent.availableWidgets), so the tier IS
    // its gate — an absent explicit entry means "no extra tier restriction",
    // i.e. visible, NOT locked. (Explicit entries still tier-gate specific
    // widgets, e.g. greeks is locked for beginners.) Non-widget features
    // (routes, capabilities) still fail closed to locked.
    return featureId.startsWith("widget:") ? "visible" : "locked";
  }
  return gate[level];
}
